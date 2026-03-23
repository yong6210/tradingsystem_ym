# MICRO_LIVE Preflight

- generated_at: 2026-03-09T05:52:47.215001+00:00
- symbol: BTCUSDC
- universe: usdc_perp_top30
- overall_status: NOT_READY

## Key Decision

- result: NOT_READY
- summary: 2 blocking preflight check(s) remain.

## Checks

- [PASS] health_ready: health status=ready checks={'db': True, 'binance_rest': True, 'event_backend': True}
- [PASS] auto_trading_enabled: execution_mode=PAPER
- [PASS] new_entries_allowed: new entries allowed
- [FAIL] validation_language: NO_GO: NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval.
- [FAIL] checklist_language: NO_GO: NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval.
- [PASS] safety_state: kill=False close_only=False config_close_only=False
- [PASS] reconciliation: healthy=True severity=INFO
- [PASS] alert_channel: latest_validation_alert=True
- [PASS] candidate_available: BTCUSDC legacy_zone_plan GO

## Candidate

- plan_id: plan_zone_2682a953a959_confirm
- symbol: BTCUSDC
- family: legacy_zone_plan
- deployment: GO
- expected_summary: win≈48.1%, EV≈+0.34R, TP1≈56.5%, TP2≈41.2%, TP3≈25.9%

## Next Steps

- NO_GO: NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval.
- NO_GO: NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval.

## Raw Payload

```json
{
  "generated_at": "2026-03-09T05:52:47.215001+00:00",
  "symbol": "BTCUSDC",
  "universe": "usdc_perp_top30",
  "overall_status": "NOT_READY",
  "summary_line": "2 blocking preflight check(s) remain.",
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
      "status": "PASS",
      "message": "BTCUSDC legacy_zone_plan GO"
    }
  ],
  "candidate": {
    "symbol": "BTCUSDC",
    "plan_id": "plan_zone_2682a953a959_confirm",
    "zone_id": "zone_2682a953a959",
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
        "start": "2026-03-09T05:52:47.588088+00:00",
        "end": "2026-03-09T05:52:47.588088+00:00",
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
        "start": "2026-03-09T05:52:47.588088+00:00",
        "end": "2026-03-09T05:52:47.588088+00:00",
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
      "entry_model": "CONFIRM",
      "factors": {
        "grade_risk": 0.5,
        "regime_factor": 0.8,
        "reaction_factor": 1.0,
        "thesis_factor": 0.6,
        "execution_factor": 0.85
      },
      "final_risk_r": 0.204,
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
    "recommended_risk_r": 0.204,
    "expected_win_prob": 0.4807,
    "expected_ev_r": 0.3438,
    "expected_tp1_prob": 0.5646,
    "expected_tp2_prob": 0.4117,
    "expected_tp3_prob": 0.2588,
    "expected_ev_at_recommended_size_r": 0.0,
    "expected_summary": "win≈48.1%, EV≈+0.34R, TP1≈56.5%, TP2≈41.2%, TP3≈25.9%",
    "entry_condition": "touch then confirm",
    "why_now": "strategy family not applicable",
    "operator_status": "accepted",
    "block_reason": null,
    "block_reason_message": null,
    "entry_model": "CONFIRM",
    "regime": "range",
    "final_rank_score": -5.0693,
    "ev": 0.3437532646282749,
    "rr_base": 2.0,
    "friction_penalty": 9.836,
    "portfolio_penalty": 52.5888,
    "portfolio_high_corr_count": 0,
    "risk_budget_score": 47.4112,
    "portfolio_volatility": 0.022147,
    "portfolio_total_cap": 10,
    "portfolio_directional_cap": 6,
    "portfolio_cluster_cap": 2,
    "thesis_fingerprint": {
      "direction": "short",
      "regime": "range",
      "strategy_family": "legacy_zone_plan",
      "liquidity_narrative": "range_upper_reject",
      "event_classification": "mixed",
      "time_bucket": "2026-03-09T05:30Z_30m",
      "correlation_cluster": "btc_beta"
    },
    "thesis_cluster_id": "short:range:legacy_zone_plan:range_upper_reject:mixed:2026-03-09T05:30Z_30m:btc_beta",
    "thesis_cluster_size": 1,
    "thesis_primary_symbol": "BTCUSDC",
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
    "generated_at": "2026-03-09T05:52:47.336722Z",
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
    "active_locks": [],
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
        "total": 34,
        "attempted": 11,
        "delivered": 9,
        "skipped": 23,
        "failed": 2,
        "success_rate": 0.8181818181818182,
        "failure_rate": 0.18181818181818182,
        "skipped_rate": 0.6764705882352942,
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
          "queued": 4
        },
        "backlog_age_seconds": 3257,
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
        "alert_id": "val_warn_e06e597cb5_VALD1773032312USDC",
        "symbol": "VALD1773032312USDC",
        "channel": "discord",
        "type": "validation_warn",
        "triggered_ts": "2026-03-09T04:58:32.069807",
        "status": "WARN",
        "deployment_go_no_go": "NO_GO",
        "deployment_code": "no_go_threshold_lineage_winner_unresolved",
        "deployment_message": "NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval.",
        "approval_topline_summary_line": "winner=unresolved/unknown; worst=latency_plus_1_bar/WARN/approximation; promotion=keep_current_path",
        "approval_playbook_go_no_go": "NO_GO",
        "approval_playbook_code": "no_go_threshold_lineage_winner_unresolved",
        "approval_playbook_action": "resolve_selected_trial_lineage_before_rollout",
        "approval_playbook_message": "NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval.",
        "delivery_reason": "delivered",
        "delivery_channel": "discord",
        "delivered": true,
        "skipped": false,
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
    "generated_at": "2026-03-09T05:52:47.340830Z"
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
    "active_locks": [],
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
      "alert_id": "val_warn_e06e597cb5_VALD1773032312USDC",
      "symbol": "VALD1773032312USDC",
      "channel": "discord",
      "type": "validation_warn",
      "triggered_ts": "2026-03-09T04:58:32.069807",
      "status": "WARN",
      "deployment_go_no_go": "NO_GO",
      "deployment_code": "no_go_threshold_lineage_winner_unresolved",
      "deployment_message": "NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval.",
      "approval_topline_summary_line": "winner=unresolved/unknown; worst=latency_plus_1_bar/WARN/approximation; promotion=keep_current_path",
      "approval_playbook_go_no_go": "NO_GO",
      "approval_playbook_code": "no_go_threshold_lineage_winner_unresolved",
      "approval_playbook_action": "resolve_selected_trial_lineage_before_rollout",
      "approval_playbook_message": "NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval.",
      "delivery_reason": "delivered",
      "delivery_channel": "discord",
      "delivered": true,
      "skipped": false,
      "failed": false,
      "retry_queued": 0
    },
    "overall": {
      "scope": "leaf_channels",
      "total": 34,
      "attempted": 11,
      "delivered": 9,
      "skipped": 23,
      "failed": 2,
      "success_rate": 0.8181818181818182,
      "failure_rate": 0.18181818181818182,
      "skipped_rate": 0.6764705882352942,
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
    "NO_GO: NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval.",
    "NO_GO: NO-GO: selected-trial lineage winner is unresolved. Resolve threshold lineage first, then rerun approval."
  ]
}
```