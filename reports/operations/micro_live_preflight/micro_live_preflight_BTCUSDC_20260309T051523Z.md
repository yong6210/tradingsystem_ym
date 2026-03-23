# MICRO_LIVE Preflight

- generated_at: 2026-03-09T05:15:23.675842+00:00
- symbol: BTCUSDC
- universe: usdc_perp_top30
- overall_status: NOT_READY

## Key Decision

- result: NOT_READY
- summary: 4 blocking preflight check(s) remain.

## Checks

- [PASS] health_ready: health status=ready checks={'db': True, 'binance_rest': True, 'event_backend': True}
- [FAIL] auto_trading_enabled: execution_mode=SHADOW
- [PASS] new_entries_allowed: new entries allowed
- [FAIL] validation_language: NO_GO: NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval.
- [FAIL] checklist_language: NO_GO: NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval.
- [PASS] safety_state: kill=False close_only=False config_close_only=False
- [FAIL] reconciliation: healthy=False severity=CRITICAL
- [PASS] alert_channel: latest_validation_alert=True
- [PASS] candidate_available: SUIUSDC legacy_zone_plan GO

## Candidate

- plan_id: plan_zone_d7c172d4c6ee_sweep_confirm
- symbol: SUIUSDC
- family: legacy_zone_plan
- deployment: GO
- expected_summary: win≈47.8%, EV≈+0.08R, TP1≈56.3%, TP2≈41.0%, TP3≈25.8%

## Next Steps

- execution_mode=SHADOW
- NO_GO: NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval.
- NO_GO: NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval.
- healthy=False severity=CRITICAL

## Raw Payload

```json
{
  "generated_at": "2026-03-09T05:15:23.675842+00:00",
  "symbol": "BTCUSDC",
  "universe": "usdc_perp_top30",
  "overall_status": "NOT_READY",
  "summary_line": "4 blocking preflight check(s) remain.",
  "checks": [
    {
      "name": "health_ready",
      "status": "PASS",
      "message": "health status=ready checks={'db': True, 'binance_rest': True, 'event_backend': True}"
    },
    {
      "name": "auto_trading_enabled",
      "status": "FAIL",
      "message": "execution_mode=SHADOW"
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
      "status": "FAIL",
      "message": "healthy=False severity=CRITICAL"
    },
    {
      "name": "alert_channel",
      "status": "PASS",
      "message": "latest_validation_alert=True"
    },
    {
      "name": "candidate_available",
      "status": "PASS",
      "message": "SUIUSDC legacy_zone_plan GO"
    }
  ],
  "candidate": {
    "symbol": "SUIUSDC",
    "plan_id": "plan_zone_d7c172d4c6ee_sweep_confirm",
    "zone_id": "zone_d7c172d4c6ee",
    "direction": "short",
    "strategy_mode": "A_ONLY",
    "deployment_go_no_go": "GO",
    "deployment_code": "go_runtime_gate_open",
    "deployment_message": "GO: runtime gate is open for candidate review.",
    "risk_reason": "normal",
    "operating_lock": {
      "state": "OPEN",
      "active": false,
      "enforced": true,
      "reason": "normal",
      "scope": "none",
      "strategy_mode": "A_ONLY",
      "unlock_at": null,
      "current_session": {
        "name": "inactive",
        "start": "2026-03-09T05:15:25.076013+00:00",
        "end": "2026-03-09T05:15:25.076013+00:00",
        "active": false
      },
      "daily_stats": {
        "trades": 0,
        "realized_r": 0,
        "loss_streak": 0,
        "a_grade_loss_streak": 0,
        "last_trade": null,
        "loss_limit_r": -2.0
      },
      "session_stats": {
        "trades": 0,
        "realized_r": 0,
        "loss_streak": 0,
        "last_trade": null,
        "loss_limit_r": -1.5
      }
    },
    "session_guidance": {
      "state": "dead_session",
      "status": "WARN",
      "summary": "current window is dead session; live entries are guidance-only discouraged",
      "strategy_mode": "A_ONLY",
      "current_session": {
        "name": "inactive",
        "start": "2026-03-09T05:15:25.076013+00:00",
        "end": "2026-03-09T05:15:25.076013+00:00",
        "active": false
      },
      "dead_session": true,
      "session_lock_active": false,
      "preferred_sessions": [
        "london",
        "new_york",
        "overlap"
      ],
      "preferred_windows_utc": {
        "london": {
          "start": "2026-03-09T07:00:00+00:00",
          "end": "2026-03-09T12:00:00+00:00",
          "active": false
        },
        "new_york": {
          "start": "2026-03-09T13:00:00+00:00",
          "end": "2026-03-09T18:00:00+00:00",
          "active": false
        },
        "overlap": {
          "start": "2026-03-09T13:00:00+00:00",
          "end": "2026-03-09T12:00:00+00:00",
          "defined": false,
          "active": false
        }
      },
      "soft_penalty": 6.0,
      "unlock_at": null,
      "engine_dead_session_hard_block": false,
      "routing_policy": "guidance_only_soft_penalty"
    },
    "session_penalty": 6.0,
    "strategy_family": "legacy_zone_plan",
    "strategy_grade": null,
    "strategy_family_reason": "strategy_family_not_applicable",
    "strategy_scorecard": {},
    "strategy_scorecard_buckets": {},
    "strategy_scorecard_raw_components": {},
    "strategy_sizing": {
      "schema_version": "v2",
      "strategy_family": "legacy_zone_plan",
      "strategy_grade": "B",
      "grade_source": "legacy_default_b",
      "active_thesis_clusters": 1,
      "transition_state": "none",
      "reaction_classification": "not_applicable",
      "confirm_only": false,
      "entry_model": "SWEEP_CONFIRM",
      "factors": {
        "grade_risk": 0.5,
        "regime_factor": 0.8,
        "reaction_factor": 1.0,
        "thesis_factor": 0.6,
        "execution_factor": 0.75
      },
      "final_risk_r": 0.18,
      "blocked": false,
      "blocked_reason": "active_thesis_size_clamp",
      "notes": {
        "regime": null,
        "reaction": null,
        "thesis": "active_thesis_size_clamp"
      },
      "strategy_mode": "A_ONLY",
      "shadow_only": false,
      "mode_policy": {
        "mode": "A_ONLY",
        "allowed_families": [
          "sweep_reversal",
          "trend_continuation"
        ],
        "allowed_grades": [
          "A"
        ],
        "max_daily_trades": 3,
        "max_total_risk_r": 1.5,
        "shadow_only": false
      }
    },
    "recommended_risk_r": 0.18,
    "expected_win_prob": 0.4784,
    "expected_ev_r": 0.0787,
    "expected_tp1_prob": 0.5629,
    "expected_tp2_prob": 0.4103,
    "expected_tp3_prob": 0.2577,
    "expected_ev_at_recommended_size_r": 0.0236,
    "expected_summary": "win≈47.8%, EV≈+0.08R, TP1≈56.3%, TP2≈41.0%, TP3≈25.8%",
    "entry_condition": "touch then confirm",
    "why_now": "strategy family not applicable",
    "operator_status": "accepted",
    "block_reason": null,
    "block_reason_message": null,
    "entry_model": "SWEEP_CONFIRM",
    "regime": "range",
    "final_rank_score": -1.907,
    "ev": 0.0786598671627074,
    "rr_base": 1.92762148337605,
    "friction_penalty": 32.19,
    "portfolio_penalty": 0.0,
    "portfolio_high_corr_count": 0,
    "risk_budget_score": 100.0,
    "portfolio_volatility": 0.003072,
    "portfolio_total_cap": 10,
    "portfolio_directional_cap": 6,
    "portfolio_cluster_cap": 2,
    "thesis_fingerprint": {
      "direction": "short",
      "regime": "range",
      "strategy_family": "legacy_zone_plan",
      "liquidity_narrative": "range_upper_reject",
      "event_classification": "mixed",
      "time_bucket": "2026-03-09T05:00Z_30m",
      "correlation_cluster": "others"
    },
    "thesis_cluster_id": "short:range:legacy_zone_plan:range_upper_reject:mixed:2026-03-09T05:00Z_30m:others",
    "thesis_cluster_size": 1,
    "thesis_primary_symbol": "SUIUSDC",
    "thesis_rejected_reason": null,
    "thesis_active_cluster_count": 2
  },
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
    "generated_at": "2026-03-09T05:15:23.903361Z",
    "symbol": "BTCUSDC",
    "execution_mode": "SHADOW",
    "auto_trading_enabled": false,
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
        "lock_id": "lock_65314a522a3b4136bf3d",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1773032311154419USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1773032311154419USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-09T04:58:31.158969Z",
        "updated_at": "2026-03-09T04:58:31.158973Z"
      },
      {
        "lock_id": "lock_3f1abdd9ee3147498e38",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1773031832274538USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1773031832274538USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-09T04:50:32.288802Z",
        "updated_at": "2026-03-09T04:50:32.288806Z"
      },
      {
        "lock_id": "lock_be57eb3767644f9489fd",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1773031830603971USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1773031830603971USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-09T04:50:30.608544Z",
        "updated_at": "2026-03-09T04:50:30.608546Z"
      },
      {
        "lock_id": "lock_b4ac8af879564d0da33b",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1773031686313014USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1773031686313014USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-09T04:48:06.317015Z",
        "updated_at": "2026-03-09T04:48:06.317016Z"
      },
      {
        "lock_id": "lock_14442128c0f34858b620",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1773031361893584USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1773031361893584USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-09T04:42:41.899126Z",
        "updated_at": "2026-03-09T04:42:41.899127Z"
      },
      {
        "lock_id": "lock_9f358ed0878d4286b07b",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1773030085046849USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1773030085046849USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-09T04:21:25.051470Z",
        "updated_at": "2026-03-09T04:21:25.051471Z"
      },
      {
        "lock_id": "lock_88d8cddadc9e4cc09fc2",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1773030074841450USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1773030074841450USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-09T04:21:14.848188Z",
        "updated_at": "2026-03-09T04:21:14.848190Z"
      },
      {
        "lock_id": "lock_2908b71bda6f42a0a56d",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1773030033011466USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1773030033011466USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-09T04:20:33.018538Z",
        "updated_at": "2026-03-09T04:20:33.018539Z"
      },
      {
        "lock_id": "lock_d50b15cdbcdf44e4b3d9",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1773000243738857USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1773000243738857USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-08T20:04:03.743902Z",
        "updated_at": "2026-03-08T20:04:03.743904Z"
      },
      {
        "lock_id": "lock_cff61349ba5e4b53ab29",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1772999935308367USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1772999935308367USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-08T19:58:55.311470Z",
        "updated_at": "2026-03-08T19:58:55.311470Z"
      },
      {
        "lock_id": "lock_bbc3dea3a5374d9c8763",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1772999907992291USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1772999907992291USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-08T19:58:27.996380Z",
        "updated_at": "2026-03-08T19:58:27.996381Z"
      },
      {
        "lock_id": "lock_f390cbae6b2245b28ce9",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1772999881387100USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1772999881387100USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-08T19:58:01.390482Z",
        "updated_at": "2026-03-08T19:58:01.390483Z"
      },
      {
        "lock_id": "lock_527fad3b927f46c78216",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1772999839787132USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1772999839787132USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-08T19:57:19.790853Z",
        "updated_at": "2026-03-08T19:57:19.790854Z"
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
    "recent_intent_count": 2,
    "recent_intents": [
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
    "open_order_count": 1,
    "open_orders": [
      {
        "submission_id": "sub_e861f371d53445ff867a",
        "intent_id": "intent_0264c33874f5404ba73c",
        "plan_id": "BTCUSDC_micro_live_plan_1772999839757172",
        "symbol": "BTCUSDC",
        "state": "ACKNOWLEDGED",
        "submit_status": "NEW",
        "message": "Live submit forwarded to Binance adapter.",
        "adapter": "binance",
        "execution_mode": "MICRO_LIVE",
        "client_order_id": "intent-c33874f5404ba73c",
        "exchange_order_id": "987654",
        "requested_live": true,
        "submitted_at": "2026-03-08T19:57:19.765969",
        "acknowledged_at": "2026-03-08T19:57:19.765954",
        "cancelled_at": null
      }
    ],
    "open_position_count": 0,
    "open_positions": [],
    "recent_reconciliation_count": 2,
    "recent_reconciliation_summary": {
      "healthy": false,
      "highest_severity": "CRITICAL",
      "degraded": true,
      "critical_count": 1,
      "lock_required_count": 2
    },
    "recent_reconciliation_events": [
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
      "accepted_candidate_count": 1,
      "blocked_candidate_count": 9,
      "current_position_count": 1,
      "headroom_by_regime": {
        "range": {
          "caps": {
            "total": 10,
            "directional": 6,
            "cluster": 2
          },
          "remaining_total": 9,
          "remaining_directional": {
            "long": 5,
            "short": 6
          },
          "remaining_cluster": {
            "long": 1,
            "short": 2
          },
          "current_directional": {
            "long": 1,
            "short": 0
          },
          "current_cluster": {
            "long": 1,
            "short": 0
          },
          "remaining_thesis_clusters": 1
        },
        "trend": {
          "caps": {
            "total": 8,
            "directional": 5,
            "cluster": 1
          },
          "remaining_total": 7,
          "remaining_directional": {
            "long": 4,
            "short": 5
          },
          "remaining_cluster": {
            "long": 0,
            "short": 1
          },
          "current_directional": {
            "long": 1,
            "short": 0
          },
          "current_cluster": {
            "long": 1,
            "short": 0
          },
          "remaining_thesis_clusters": 1
        },
        "shock": {
          "caps": {
            "total": 5,
            "directional": 3,
            "cluster": 1
          },
          "remaining_total": 4,
          "remaining_directional": {
            "long": 2,
            "short": 3
          },
          "remaining_cluster": {
            "long": 0,
            "short": 1
          },
          "current_directional": {
            "long": 1,
            "short": 0
          },
          "current_cluster": {
            "long": 1,
            "short": 0
          },
          "remaining_thesis_clusters": 1
        }
      }
    },
    "alert_summary": {
      "overall": {
        "scope": "leaf_channels",
        "total": 25,
        "attempted": 11,
        "delivered": 9,
        "skipped": 14,
        "failed": 2,
        "success_rate": 0.8181818181818182,
        "failure_rate": 0.18181818181818182,
        "skipped_rate": 0.56,
        "latency_ms": {
          "avg": 134.356,
          "p50": 0.003,
          "p95": 362.75699999999995,
          "max": 403.063
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
          "allowed_failures": 0.055,
          "failed": 2,
          "remaining_failures": -1.945,
          "burn_ratio": 36.36363636363633,
          "budget_fraction_remaining": 0.0
        }
      },
      "retry_queue": {
        "counts": {
          "queued": 5
        },
        "backlog_age_seconds": 1013,
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
        "alert_id": "alert_retry_arq_1773032311548078_1_1_1773032406937702",
        "symbol": "PBOENGINE1773032311503053USDC",
        "channel": "discord",
        "type": "validation_warn",
        "triggered_ts": "2026-03-09T05:00:06.937702",
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
        "lock_id": "lock_65314a522a3b4136bf3d",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1773032311154419USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1773032311154419USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-09T04:58:31.158969Z",
        "updated_at": "2026-03-09T04:58:31.158973Z"
      },
      {
        "lock_id": "lock_3f1abdd9ee3147498e38",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1773031832274538USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1773031832274538USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-09T04:50:32.288802Z",
        "updated_at": "2026-03-09T04:50:32.288806Z"
      },
      {
        "lock_id": "lock_be57eb3767644f9489fd",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1773031830603971USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1773031830603971USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-09T04:50:30.608544Z",
        "updated_at": "2026-03-09T04:50:30.608546Z"
      },
      {
        "lock_id": "lock_b4ac8af879564d0da33b",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1773031686313014USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1773031686313014USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-09T04:48:06.317015Z",
        "updated_at": "2026-03-09T04:48:06.317016Z"
      },
      {
        "lock_id": "lock_14442128c0f34858b620",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1773031361893584USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1773031361893584USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-09T04:42:41.899126Z",
        "updated_at": "2026-03-09T04:42:41.899127Z"
      },
      {
        "lock_id": "lock_9f358ed0878d4286b07b",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1773030085046849USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1773030085046849USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-09T04:21:25.051470Z",
        "updated_at": "2026-03-09T04:21:25.051471Z"
      },
      {
        "lock_id": "lock_88d8cddadc9e4cc09fc2",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1773030074841450USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1773030074841450USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-09T04:21:14.848188Z",
        "updated_at": "2026-03-09T04:21:14.848190Z"
      },
      {
        "lock_id": "lock_2908b71bda6f42a0a56d",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1773030033011466USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1773030033011466USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-09T04:20:33.018538Z",
        "updated_at": "2026-03-09T04:20:33.018539Z"
      },
      {
        "lock_id": "lock_d50b15cdbcdf44e4b3d9",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1773000243738857USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1773000243738857USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-08T20:04:03.743902Z",
        "updated_at": "2026-03-08T20:04:03.743904Z"
      },
      {
        "lock_id": "lock_cff61349ba5e4b53ab29",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1772999935308367USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1772999935308367USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-08T19:58:55.311470Z",
        "updated_at": "2026-03-08T19:58:55.311470Z"
      },
      {
        "lock_id": "lock_bbc3dea3a5374d9c8763",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1772999907992291USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1772999907992291USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-08T19:58:27.996380Z",
        "updated_at": "2026-03-08T19:58:27.996381Z"
      },
      {
        "lock_id": "lock_f390cbae6b2245b28ce9",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1772999881387100USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1772999881387100USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-08T19:58:01.390482Z",
        "updated_at": "2026-03-08T19:58:01.390483Z"
      },
      {
        "lock_id": "lock_527fad3b927f46c78216",
        "scope_type": "SYMBOL",
        "scope_key": "LOCKSYM1772999839787132USDC",
        "severity": "CRITICAL",
        "reason_code": "reconciliation_missing_stop_order",
        "reason_message": "Exchange position is open but no reduce-only stop order is present.",
        "active": true,
        "allow_closes": true,
        "lock_metadata": {
          "symbol": "LOCKSYM1772999839787132USDC",
          "mismatch_type": "MISSING_STOP_ORDER",
          "severity": "CRITICAL"
        },
        "unlock_at": null,
        "released_at": null,
        "created_at": "2026-03-08T19:57:19.790853Z",
        "updated_at": "2026-03-08T19:57:19.790854Z"
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
      "alert_id": "alert_retry_arq_1773032311548078_1_1_1773032406937702",
      "symbol": "PBOENGINE1773032311503053USDC",
      "channel": "discord",
      "type": "validation_warn",
      "triggered_ts": "2026-03-09T05:00:06.937702",
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
      "total": 25,
      "attempted": 11,
      "delivered": 9,
      "skipped": 14,
      "failed": 2,
      "success_rate": 0.8181818181818182,
      "failure_rate": 0.18181818181818182,
      "skipped_rate": 0.56,
      "latency_ms": {
        "avg": 134.356,
        "p50": 0.003,
        "p95": 362.75699999999995,
        "max": 403.063
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
        "allowed_failures": 0.055,
        "failed": 2,
        "remaining_failures": -1.945,
        "burn_ratio": 36.36363636363633,
        "budget_fraction_remaining": 0.0
      }
    }
  },
  "next_steps": [
    "execution_mode=SHADOW",
    "NO_GO: NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval.",
    "NO_GO: NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval.",
    "healthy=False severity=CRITICAL"
  ]
}
```