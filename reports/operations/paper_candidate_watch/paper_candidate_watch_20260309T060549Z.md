# PAPER Candidate Watch

- generated_at: 2026-03-09 06:05:49.796110+00:00
- overall_status: NO_ELIGIBLE_CANDIDATE
- summary: No eligible PAPER lineage candidate found after 8 attempt(s).
- attempts_run: 8

## Attempts

- attempt 1: NOT_READY / 1 blocking drill check(s) remain.
- attempt 2: NOT_READY / 1 blocking drill check(s) remain.
- attempt 3: NOT_READY / 1 blocking drill check(s) remain.
- attempt 4: NOT_READY / 1 blocking drill check(s) remain.
- attempt 5: NOT_READY / 1 blocking drill check(s) remain.
- attempt 6: NOT_READY / 1 blocking drill check(s) remain.
- attempt 7: NOT_READY / 1 blocking drill check(s) remain.
- attempt 8: NOT_READY / 1 blocking drill check(s) remain.

## Raw Payload

```json
{
  "generated_at": "2026-03-09T06:05:49.796110+00:00",
  "overall_status": "NO_ELIGIBLE_CANDIDATE",
  "summary_line": "No eligible PAPER lineage candidate found after 8 attempt(s).",
  "attempts_run": 8,
  "families": [
    "trend_continuation",
    "sweep_reversal"
  ],
  "submit_paper": true,
  "interval_seconds": 900,
  "max_attempts": 8,
  "attempts": [
    {
      "attempt": 1,
      "generated_at": "2026-03-09T06:05:49.859313+00:00",
      "overall_status": "NOT_READY",
      "summary_line": "1 blocking drill check(s) remain.",
      "eligible_candidate_found": false,
      "candidate": null,
      "submission": null,
      "report_path": null
    },
    {
      "attempt": 2,
      "generated_at": "2026-03-09T06:20:52.641852+00:00",
      "overall_status": "NOT_READY",
      "summary_line": "1 blocking drill check(s) remain.",
      "eligible_candidate_found": false,
      "candidate": null,
      "submission": null,
      "report_path": null
    },
    {
      "attempt": 3,
      "generated_at": "2026-03-09T06:35:55.420812+00:00",
      "overall_status": "NOT_READY",
      "summary_line": "1 blocking drill check(s) remain.",
      "eligible_candidate_found": false,
      "candidate": null,
      "submission": null,
      "report_path": null
    },
    {
      "attempt": 4,
      "generated_at": "2026-03-09T06:50:58.252748+00:00",
      "overall_status": "NOT_READY",
      "summary_line": "1 blocking drill check(s) remain.",
      "eligible_candidate_found": false,
      "candidate": null,
      "submission": null,
      "report_path": null
    },
    {
      "attempt": 5,
      "generated_at": "2026-03-09T07:06:01.084664+00:00",
      "overall_status": "NOT_READY",
      "summary_line": "1 blocking drill check(s) remain.",
      "eligible_candidate_found": false,
      "candidate": null,
      "submission": null,
      "report_path": null
    },
    {
      "attempt": 6,
      "generated_at": "2026-03-09T07:21:06.934292+00:00",
      "overall_status": "NOT_READY",
      "summary_line": "1 blocking drill check(s) remain.",
      "eligible_candidate_found": false,
      "candidate": null,
      "submission": null,
      "report_path": null
    },
    {
      "attempt": 7,
      "generated_at": "2026-03-09T07:36:09.813126+00:00",
      "overall_status": "NOT_READY",
      "summary_line": "1 blocking drill check(s) remain.",
      "eligible_candidate_found": false,
      "candidate": null,
      "submission": null,
      "report_path": null
    },
    {
      "attempt": 8,
      "generated_at": "2026-03-09T07:51:12.778596+00:00",
      "overall_status": "NOT_READY",
      "summary_line": "1 blocking drill check(s) remain.",
      "eligible_candidate_found": false,
      "candidate": null,
      "submission": null,
      "report_path": null
    }
  ],
  "final_result": {
    "generated_at": "2026-03-09T07:51:12.778596+00:00",
    "symbol": null,
    "universe": "usdc_perp_top30",
    "families": [
      "sweep_reversal",
      "trend_continuation"
    ],
    "paper_lineage_override": false,
    "overall_status": "NOT_READY",
    "summary_line": "1 blocking drill check(s) remain.",
    "checks": [
      {
        "name": "universe_sync",
        "status": "PASS",
        "message": "success=30 failed=0 processed=30"
      },
      {
        "name": "eligible_candidate_found",
        "status": "FAIL",
        "message": "No eligible trend_continuation/sweep_reversal candidate found in scanner output."
      }
    ],
    "sync": {
      "universe": "usdc_perp_top30",
      "requested_symbols": 30,
      "processed_symbols": 30,
      "symbol_concurrency_requested": 4,
      "symbol_concurrency": 4,
      "execution_mode": "parallel",
      "success": 30,
      "failed": 0,
      "results": [
        {
          "symbol": "BTCUSDC",
          "status": "ok",
          "backfill": {
            "1m": 17,
            "5m": 4,
            "15m": 2,
            "total": 23
          },
          "refresh": {
            "symbol": "BTCUSDC",
            "updated": true,
            "zones": 160,
            "plans": 5,
            "risk_state": "OPEN",
            "gate_reason": "normal",
            "operating_lock": {
              "state": "OPEN",
              "active": false,
              "enforced": true,
              "reason": "normal",
              "scope": "none",
              "strategy_mode": "A_ONLY",
              "unlock_at": null,
              "current_session": {
                "name": "london",
                "start": "2026-03-09T07:00:00+00:00",
                "end": "2026-03-09T12:00:00+00:00",
                "active": true
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
            "regime_label": "range",
            "transition_score": 35.0,
            "transition_state": "none",
            "transition_lock_reason": null,
            "active_thesis_clusters": 9,
            "strategy_mode": "A_ONLY",
            "feature_calibration_available": false,
            "feature_calibration_samples": 0,
            "signal_alerts": {
              "near": 0,
              "touch": 0,
              "confirm": 0,
              "emitted_total": 0
            }
          }
        },
        {
          "symbol": "ETHUSDC",
          "status": "ok",
          "backfill": {
            "1m": 16,
            "5m": 4,
            "15m": 2,
            "total": 22
          },
          "refresh": {
            "symbol": "ETHUSDC",
            "updated": true,
            "zones": 75,
            "plans": 0,
            "risk_state": "OPEN",
            "gate_reason": "normal",
            "operating_lock": {
              "state": "OPEN",
              "active": false,
              "enforced": true,
              "reason": "normal",
              "scope": "none",
              "strategy_mode": "A_ONLY",
              "unlock_at": null,
              "current_session": {
                "name": "london",
                "start": "2026-03-09T07:00:00+00:00",
                "end": "2026-03-09T12:00:00+00:00",
                "active": true
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
            "regime_label": "transition",
            "transition_score": 49.0,
            "transition_state": "transition_confirmed",
            "transition_lock_reason": "transition_hard_override_information_failure",
            "active_thesis_clusters": 9,
            "strategy_mode": "A_ONLY",
            "feature_calibration_available": false,
            "feature_calibration_samples": 0,
            "signal_alerts": {
              "near": 0,
              "touch": 0,
              "confirm": 0,
              "emitted_total": 0
            }
          }
        },
        {
          "symbol": "SOLUSDC",
          "status": "ok",
          "backfill": {
            "1m": 16,
            "5m": 4,
            "15m": 2,
            "total": 22
          },
          "refresh": {
            "symbol": "SOLUSDC",
            "updated": true,
            "zones": 77,
            "plans": 3,
            "risk_state": "OPEN",
            "gate_reason": "normal",
            "operating_lock": {
              "state": "OPEN",
              "active": false,
              "enforced": true,
              "reason": "normal",
              "scope": "none",
              "strategy_mode": "A_ONLY",
              "unlock_at": null,
              "current_session": {
                "name": "london",
                "start": "2026-03-09T07:00:00+00:00",
                "end": "2026-03-09T12:00:00+00:00",
                "active": true
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
            "regime_label": "range",
            "transition_score": 49.0,
            "transition_state": "transition_watch",
            "transition_lock_reason": "transition_score_watch",
            "active_thesis_clusters": 9,
            "strategy_mode": "A_ONLY",
            "feature_calibration_available": false,
            "feature_calibration_samples": 0,
            "signal_alerts": {
              "near": 2,
              "touch": 1,
              "confirm": 0,
              "emitted_total": 0
            }
          }
        },
        {
          "symbol": "XRPUSDC",
          "status": "ok",
          "backfill": {
            "1m": 16,
            "5m": 4,
            "15m": 2,
            "total": 22
          },
          "refresh": {
            "symbol": "XRPUSDC",
            "updated": true,
            "zones": 71,
            "plans": 2,
            "risk_state": "OPEN",
            "gate_reason": "normal",
            "operating_lock": {
              "state": "OPEN",
              "active": false,
              "enforced": true,
              "reason": "normal",
              "scope": "none",
              "strategy_mode": "A_ONLY",
              "unlock_at": null,
              "current_session": {
                "name": "london",
                "start": "2026-03-09T07:00:00+00:00",
                "end": "2026-03-09T12:00:00+00:00",
                "active": true
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
            "regime_label": "range",
            "transition_score": 34.0,
            "transition_state": "none",
            "transition_lock_reason": null,
            "active_thesis_clusters": 9,
            "strategy_mode": "A_ONLY",
            "feature_calibration_available": false,
            "feature_calibration_samples": 0,
            "signal_alerts": {
              "near": 0,
              "touch": 0,
              "confirm": 0,
              "emitted_total": 0
            }
          }
        },
        {
          "symbol": "BNBUSDC",
          "status": "ok",
          "backfill": {
            "1m": 16,
            "5m": 4,
            "15m": 2,
            "total": 22
          },
          "refresh": {
            "symbol": "BNBUSDC",
            "updated": true,
            "zones": 72,
            "plans": 3,
            "risk_state": "OPEN",
            "gate_reason": "normal",
            "operating_lock": {
              "state": "OPEN",
              "active": false,
              "enforced": true,
              "reason": "normal",
              "scope": "none",
              "strategy_mode": "A_ONLY",
              "unlock_at": null,
              "current_session": {
                "name": "london",
                "start": "2026-03-09T07:00:00+00:00",
                "end": "2026-03-09T12:00:00+00:00",
                "active": true
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
            "regime_label": "range",
            "transition_score": 34.0,
            "transition_state": "none",
            "transition_lock_reason": null,
            "active_thesis_clusters": 9,
            "strategy_mode": "A_ONLY",
            "feature_calibration_available": false,
            "feature_calibration_samples": 0,
            "signal_alerts": {
              "near": 0,
              "touch": 2,
              "confirm": 2,
              "emitted_total": 0
            }
          }
        },
        {
          "symbol": "DOGEUSDC",
          "status": "ok",
          "backfill": {
            "1m": 16,
            "5m": 4,
            "15m": 2,
            "total": 22
          },
          "refresh": {
            "symbol": "DOGEUSDC",
            "updated": true,
            "zones": 78,
            "plans": 1,
            "risk_state": "OPEN",
            "gate_reason": "normal",
            "operating_lock": {
              "state": "OPEN",
              "active": false,
              "enforced": true,
              "reason": "normal",
              "scope": "none",
              "strategy_mode": "A_ONLY",
              "unlock_at": null,
              "current_session": {
                "name": "london",
                "start": "2026-03-09T07:00:00+00:00",
                "end": "2026-03-09T12:00:00+00:00",
                "active": true
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
            "regime_label": "range",
            "transition_score": 53.0,
            "transition_state": "transition_watch",
            "transition_lock_reason": "transition_score_watch",
            "active_thesis_clusters": 9,
            "strategy_mode": "A_ONLY",
            "feature_calibration_available": false,
            "feature_calibration_samples": 0,
            "signal_alerts": {
              "near": 0,
              "touch": 0,
              "confirm": 0,
              "emitted_total": 0
            }
          }
        },
        {
          "symbol": "ZECUSDC",
          "status": "ok",
          "backfill": {
            "1m": 16,
            "5m": 4,
            "15m": 2,
            "total": 22
          },
          "refresh": {
            "symbol": "ZECUSDC",
            "updated": true,
            "zones": 87,
            "plans": 0,
            "risk_state": "OPEN",
            "gate_reason": "normal",
            "operating_lock": {
              "state": "OPEN",
              "active": false,
              "enforced": true,
              "reason": "normal",
              "scope": "none",
              "strategy_mode": "A_ONLY",
              "unlock_at": null,
              "current_session": {
                "name": "london",
                "start": "2026-03-09T07:00:00+00:00",
                "end": "2026-03-09T12:00:00+00:00",
                "active": true
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
            "regime_label": "transition",
            "transition_score": 49.0,
            "transition_state": "transition_confirmed",
            "transition_lock_reason": "transition_hard_override_information_failure",
            "active_thesis_clusters": 9,
            "strategy_mode": "A_ONLY",
            "feature_calibration_available": false,
            "feature_calibration_samples": 0,
            "signal_alerts": {
              "near": 0,
              "touch": 0,
              "confirm": 0,
              "emitted_total": 0
            }
          }
        },
        {
          "symbol": "SUIUSDC",
          "status": "ok",
          "backfill": {
            "1m": 16,
            "5m": 4,
            "15m": 2,
            "total": 22
          },
          "refresh": {
            "symbol": "SUIUSDC",
            "updated": true,
            "zones": 71,
            "plans": 3,
            "risk_state": "OPEN",
            "gate_reason": "normal",
            "operating_lock": {
              "state": "OPEN",
              "active": false,
              "enforced": true,
              "reason": "normal",
              "scope": "none",
              "strategy_mode": "A_ONLY",
              "unlock_at": null,
              "current_session": {
                "name": "london",
                "start": "2026-03-09T07:00:00+00:00",
                "end": "2026-03-09T12:00:00+00:00",
                "active": true
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
            "regime_label": "range",
            "transition_score": 52.0,
            "transition_state": "transition_watch",
            "transition_lock_reason": "transition_score_watch",
            "active_thesis_clusters": 9,
            "strategy_mode": "A_ONLY",
            "feature_calibration_available": false,
            "feature_calibration_samples": 0,
            "signal_alerts": {
              "near": 0,
              "touch": 0,
              "confirm": 0,
              "emitted_total": 0
            }
          }
        },
        {
          "symbol": "1000PEPEUSDC",
          "status": "ok",
          "backfill": {
            "1m": 16,
            "5m": 4,
            "15m": 2,
            "total": 22
          },
          "refresh": {
            "symbol": "1000PEPEUSDC",
            "updated": true,
            "zones": 77,
            "plans": 8,
            "risk_state": "OPEN",
            "gate_reason": "normal",
            "operating_lock": {
              "state": "OPEN",
              "active": false,
              "enforced": true,
              "reason": "normal",
              "scope": "none",
              "strategy_mode": "A_ONLY",
              "unlock_at": null,
              "current_session": {
                "name": "london",
                "start": "2026-03-09T07:00:00+00:00",
                "end": "2026-03-09T12:00:00+00:00",
                "active": true
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
            "regime_label": "range",
            "transition_score": 20.0,
            "transition_state": "none",
            "transition_lock_reason": null,
            "active_thesis_clusters": 9,
            "strategy_mode": "A_ONLY",
            "feature_calibration_available": false,
            "feature_calibration_samples": 0,
            "signal_alerts": {
              "near": 0,
              "touch": 1,
              "confirm": 1,
              "emitted_total": 0
            }
          }
        },
        {
          "symbol": "BCHUSDC",
          "status": "ok",
          "backfill": {
            "1m": 16,
            "5m": 4,
            "15m": 2,
            "total": 22
          },
          "refresh": {
            "symbol": "BCHUSDC",
            "updated": true,
            "zones": 69,
            "plans": 0,
            "risk_state": "OPEN",
            "gate_reason": "normal",
            "operating_lock": {
              "state": "OPEN",
              "active": false,
              "enforced": true,
              "reason": "normal",
              "scope": "none",
              "strategy_mode": "A_ONLY",
              "unlock_at": null,
              "current_session": {
                "name": "london",
                "start": "2026-03-09T07:00:00+00:00",
                "end": "2026-03-09T12:00:00+00:00",
                "active": true
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
            "regime_label": "transition",
            "transition_score": 67.0,
            "transition_state": "transition_confirmed",
            "transition_lock_reason": "transition_hard_override_information_failure",
            "active_thesis_clusters": 9,
            "strategy_mode": "A_ONLY",
            "feature_calibration_available": false,
            "feature_calibration_samples": 0,
            "signal_alerts": {
              "near": 0,
              "touch": 0,
              "confirm": 0,
              "emitted_total": 0
            }
          }
        },
        {
          "symbol": "ADAUSDC",
          "status": "ok",
          "backfill": {
            "1m": 16,
            "5m": 4,
            "15m": 2,
            "total": 22
          },
          "refresh": {
            "symbol": "ADAUSDC",
            "updated": true,
            "zones": 71,
            "plans": 3,
            "risk_state": "OPEN",
            "gate_reason": "normal",
            "operating_lock": {
              "state": "OPEN",
              "active": false,
              "enforced": true,
              "reason": "normal",
              "scope": "none",
              "strategy_mode": "A_ONLY",
              "unlock_at": null,
              "current_session": {
                "name": "london",
                "start": "2026-03-09T07:00:00+00:00",
                "end": "2026-03-09T12:00:00+00:00",
                "active": true
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
            "regime_label": "range",
            "transition_score": 34.0,
            "transition_state": "none",
            "transition_lock_reason": null,
            "active_thesis_clusters": 9,
            "strategy_mode": "A_ONLY",
            "feature_calibration_available": false,
            "feature_calibration_samples": 0,
            "signal_alerts": {
              "near": 0,
              "touch": 0,
              "confirm": 0,
              "emitted_total": 0
            }
          }
        },
        {
          "symbol": "LINKUSDC",
          "status": "ok",
          "backfill": {
            "1m": 16,
            "5m": 4,
            "15m": 2,
            "total": 22
          },
          "refresh": {
            "symbol": "LINKUSDC",
            "updated": true,
            "zones": 74,
            "plans": 5,
            "risk_state": "OPEN",
            "gate_reason": "normal",
            "operating_lock": {
              "state": "OPEN",
              "active": false,
              "enforced": true,
              "reason": "normal",
              "scope": "none",
              "strategy_mode": "A_ONLY",
              "unlock_at": null,
              "current_session": {
                "name": "london",
                "start": "2026-03-09T07:00:00+00:00",
                "end": "2026-03-09T12:00:00+00:00",
                "active": true
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
            "regime_label": "range",
            "transition_score": 34.0,
            "transition_state": "none",
            "transition_lock_reason": null,
            "active_thesis_clusters": 9,
            "strategy_mode": "A_ONLY",
            "feature_calibration_available": false,
            "feature_calibration_samples": 0,
            "signal_alerts": {
              "near": 0,
              "touch": 0,
              "confirm": 0,
              "emitted_total": 0
            }
          }
        },
        {
          "symbol": "AVAXUSDC",
          "status": "ok",
          "backfill": {
            "1m": 17,
            "5m": 4,
            "15m": 2,
            "total": 23
          },
          "refresh": {
            "symbol": "AVAXUSDC",
            "updated": true,
            "zones": 83,
            "plans": 3,
            "risk_state": "OPEN",
            "gate_reason": "normal",
            "operating_lock": {
              "state": "OPEN",
              "active": false,
              "enforced": true,
              "reason": "normal",
              "scope": "none",
              "strategy_mode": "A_ONLY",
              "unlock_at": null,
              "current_session": {
                "name": "london",
                "start": "2026-03-09T07:00:00+00:00",
                "end": "2026-03-09T12:00:00+00:00",
                "active": true
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
            "regime_label": "range",
            "transition_score": 35.0,
            "transition_state": "none",
            "transition_lock_reason": null,
            "active_thesis_clusters": 9,
            "strategy_mode": "A_ONLY",
            "feature_calibration_available": false,
            "feature_calibration_samples": 0,
            "signal_alerts": {
              "near": 0,
              "touch": 0,
              "confirm": 0,
              "emitted_total": 0
            }
          }
        },
        {
          "symbol": "LTCUSDC",
          "status": "ok",
          "backfill": {
            "1m": 16,
            "5m": 4,
            "15m": 2,
            "total": 22
          },
          "refresh": {
            "symbol": "LTCUSDC",
            "updated": true,
            "zones": 72,
            "plans": 2,
            "risk_state": "OPEN",
            "gate_reason": "normal",
            "operating_lock": {
              "state": "OPEN",
              "active": false,
              "enforced": true,
              "reason": "normal",
              "scope": "none",
              "strategy_mode": "A_ONLY",
              "unlock_at": null,
              "current_session": {
                "name": "london",
                "start": "2026-03-09T07:00:00+00:00",
                "end": "2026-03-09T12:00:00+00:00",
                "active": true
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
            "regime_label": "range",
            "transition_score": 49.0,
            "transition_state": "transition_watch",
            "transition_lock_reason": "transition_score_watch",
            "active_thesis_clusters": 9,
            "strategy_mode": "A_ONLY",
            "feature_calibration_available": false,
            "feature_calibration_samples": 0,
            "signal_alerts": {
              "near": 0,
              "touch": 0,
              "confirm": 0,
              "emitted_total": 0
            }
          }
        },
        {
          "symbol": "ENAUSDC",
          "status": "ok",
          "backfill": {
            "1m": 16,
            "5m": 4,
            "15m": 2,
            "total": 22
          },
          "refresh": {
            "symbol": "ENAUSDC",
            "updated": true,
            "zones": 84,
            "plans": 8,
            "risk_state": "OPEN",
            "gate_reason": "normal",
            "operating_lock": {
              "state": "OPEN",
              "active": false,
              "enforced": true,
              "reason": "normal",
              "scope": "none",
              "strategy_mode": "A_ONLY",
              "unlock_at": null,
              "current_session": {
                "name": "london",
                "start": "2026-03-09T07:00:00+00:00",
                "end": "2026-03-09T12:00:00+00:00",
                "active": true
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
            "regime_label": "range",
            "transition_score": 34.0,
            "transition_state": "none",
            "transition_lock_reason": null,
            "active_thesis_clusters": 9,
            "strategy_mode": "A_ONLY",
            "feature_calibration_available": false,
            "feature_calibration_samples": 0,
            "signal_alerts": {
              "near": 0,
              "touch": 0,
              "confirm": 0,
              "emitted_total": 0
            }
          }
        },
        {
          "symbol": "FILUSDC",
          "status": "ok",
          "backfill": {
            "1m": 16,
            "5m": 4,
            "15m": 2,
            "total": 22
          },
          "refresh": {
            "symbol": "FILUSDC",
            "updated": true,
            "zones": 86,
            "plans": 0,
            "risk_state": "OPEN",
            "gate_reason": "normal",
            "operating_lock": {
              "state": "OPEN",
              "active": false,
              "enforced": true,
              "reason": "normal",
              "scope": "none",
              "strategy_mode": "A_ONLY",
              "unlock_at": null,
              "current_session": {
                "name": "london",
                "start": "2026-03-09T07:00:00+00:00",
                "end": "2026-03-09T12:00:00+00:00",
                "active": true
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
            "regime_label": "transition",
            "transition_score": 67.0,
            "transition_state": "transition_confirmed",
            "transition_lock_reason": "transition_score_confirmed",
            "active_thesis_clusters": 9,
            "strategy_mode": "A_ONLY",
            "feature_calibration_available": false,
            "feature_calibration_samples": 0,
            "signal_alerts": {
              "near": 0,
              "touch": 0,
              "confirm": 0,
              "emitted_total": 0
            }
          }
        },
        {
          "symbol": "CRVUSDC",
          "status": "ok",
          "backfill": {
            "1m": 16,
            "5m": 4,
            "15m": 2,
            "total": 22
          },
          "refresh": {
            "symbol": "CRVUSDC",
            "updated": true,
            "zones": 86,
            "plans": 4,
            "risk_state": "OPEN",
            "gate_reason": "normal",
            "operating_lock": {
              "state": "OPEN",
              "active": false,
              "enforced": true,
              "reason": "normal",
              "scope": "none",
              "strategy_mode": "A_ONLY",
              "unlock_at": null,
              "current_session": {
                "name": "london",
                "start": "2026-03-09T07:00:00+00:00",
                "end": "2026-03-09T12:00:00+00:00",
                "active": true
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
            "regime_label": "range",
            "transition_score": 49.0,
            "transition_state": "transition_watch",
            "transition_lock_reason": "transition_score_watch",
            "active_thesis_clusters": 9,
            "strategy_mode": "A_ONLY",
            "feature_calibration_available": false,
            "feature_calibration_samples": 0,
            "signal_alerts": {
              "near": 1,
              "touch": 0,
              "confirm": 0,
              "emitted_total": 0
            }
          }
        },
        {
          "symbol": "ARBUSDC",
          "status": "ok",
          "backfill": {
            "1m": 16,
            "5m": 4,
            "15m": 2,
            "total": 22
          },
          "refresh": {
            "symbol": "ARBUSDC",
            "updated": true,
            "zones": 75,
            "plans": 3,
            "risk_state": "OPEN",
            "gate_reason": "normal",
            "operating_lock": {
              "state": "OPEN",
              "active": false,
              "enforced": true,
              "reason": "normal",
              "scope": "none",
              "strategy_mode": "A_ONLY",
              "unlock_at": null,
              "current_session": {
                "name": "london",
                "start": "2026-03-09T07:00:00+00:00",
                "end": "2026-03-09T12:00:00+00:00",
                "active": true
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
            "regime_label": "range",
            "transition_score": 52.0,
            "transition_state": "transition_watch",
            "transition_lock_reason": "transition_score_watch",
            "active_thesis_clusters": 9,
            "strategy_mode": "A_ONLY",
            "feature_calibration_available": false,
            "feature_calibration_samples": 0,
            "signal_alerts": {
              "near": 0,
              "touch": 0,
              "confirm": 0,
              "emitted_total": 0
            }
          }
        },
        {
          "symbol": "NEARUSDC",
          "status": "ok",
          "backfill": {
            "1m": 16,
            "5m": 4,
            "15m": 2,
            "total": 22
          },
          "refresh": {
            "symbol": "NEARUSDC",
            "updated": true,
            "zones": 59,
            "plans": 3,
            "risk_state": "OPEN",
            "gate_reason": "normal",
            "operating_lock": {
              "state": "OPEN",
              "active": false,
              "enforced": true,
              "reason": "normal",
              "scope": "none",
              "strategy_mode": "A_ONLY",
              "unlock_at": null,
              "current_session": {
                "name": "london",
                "start": "2026-03-09T07:00:00+00:00",
                "end": "2026-03-09T12:00:00+00:00",
                "active": true
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
            "regime_label": "range",
            "transition_score": 35.0,
            "transition_state": "none",
            "transition_lock_reason": null,
            "active_thesis_clusters": 9,
            "strategy_mode": "A_ONLY",
            "feature_calibration_available": false,
            "feature_calibration_samples": 0,
            "signal_alerts": {
              "near": 0,
              "touch": 0,
              "confirm": 0,
              "emitted_total": 0
            }
          }
        },
        {
          "symbol": "WIFUSDC",
          "status": "ok",
          "backfill": {
            "1m": 16,
            "5m": 4,
            "15m": 2,
            "total": 22
          },
          "refresh": {
            "symbol": "WIFUSDC",
            "updated": true,
            "zones": 76,
            "plans": 7,
            "risk_state": "OPEN",
            "gate_reason": "normal",
            "operating_lock": {
              "state": "OPEN",
              "active": false,
              "enforced": true,
              "reason": "normal",
              "scope": "none",
              "strategy_mode": "A_ONLY",
              "unlock_at": null,
              "current_session": {
                "name": "london",
                "start": "2026-03-09T07:00:00+00:00",
                "end": "2026-03-09T12:00:00+00:00",
                "active": true
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
            "regime_label": "range",
            "transition_score": 34.0,
            "transition_state": "none",
            "transition_lock_reason": null,
            "active_thesis_clusters": 9,
            "strategy_mode": "A_ONLY",
            "feature_calibration_available": false,
            "feature_calibration_samples": 0,
            "signal_alerts": {
              "near": 0,
              "touch": 0,
              "confirm": 0,
              "emitted_total": 0
            }
          }
        },
        {
          "symbol": "AAVEUSDC",
          "status": "ok",
          "backfill": {
            "1m": 16,
            "5m": 4,
            "15m": 2,
            "total": 22
          },
          "refresh": {
            "symbol": "AAVEUSDC",
            "updated": true,
            "zones": 75,
            "plans": 3,
            "risk_state": "OPEN",
            "gate_reason": "normal",
            "operating_lock": {
              "state": "OPEN",
              "active": false,
              "enforced": true,
              "reason": "normal",
              "scope": "none",
              "strategy_mode": "A_ONLY",
              "unlock_at": null,
              "current_session": {
                "name": "london",
                "start": "2026-03-09T07:00:00+00:00",
                "end": "2026-03-09T12:00:00+00:00",
                "active": true
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
            "regime_label": "range",
            "transition_score": 34.0,
            "transition_state": "none",
            "transition_lock_reason": null,
            "active_thesis_clusters": 9,
            "strategy_mode": "A_ONLY",
            "feature_calibration_available": false,
            "feature_calibration_samples": 0,
            "signal_alerts": {
              "near": 0,
              "touch": 0,
              "confirm": 0,
              "emitted_total": 0
            }
          }
        },
        {
          "symbol": "WLFIUSDC",
          "status": "ok",
          "backfill": {
            "1m": 16,
            "5m": 4,
            "15m": 2,
            "total": 22
          },
          "refresh": {
            "symbol": "WLFIUSDC",
            "updated": true,
            "zones": 58,
            "plans": 5,
            "risk_state": "OPEN",
            "gate_reason": "normal",
            "operating_lock": {
              "state": "OPEN",
              "active": false,
              "enforced": true,
              "reason": "normal",
              "scope": "none",
              "strategy_mode": "A_ONLY",
              "unlock_at": null,
              "current_session": {
                "name": "london",
                "start": "2026-03-09T07:00:00+00:00",
                "end": "2026-03-09T12:00:00+00:00",
                "active": true
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
            "regime_label": "range",
            "transition_score": 49.0,
            "transition_state": "transition_watch",
            "transition_lock_reason": "transition_score_watch",
            "active_thesis_clusters": 9,
            "strategy_mode": "A_ONLY",
            "feature_calibration_available": false,
            "feature_calibration_samples": 0,
            "signal_alerts": {
              "near": 1,
              "touch": 0,
              "confirm": 0,
              "emitted_total": 0
            }
          }
        },
        {
          "symbol": "IPUSDC",
          "status": "ok",
          "backfill": {
            "1m": 16,
            "5m": 4,
            "15m": 2,
            "total": 22
          },
          "refresh": {
            "symbol": "IPUSDC",
            "updated": true,
            "zones": 91,
            "plans": 7,
            "risk_state": "OPEN",
            "gate_reason": "normal",
            "operating_lock": {
              "state": "OPEN",
              "active": false,
              "enforced": true,
              "reason": "normal",
              "scope": "none",
              "strategy_mode": "A_ONLY",
              "unlock_at": null,
              "current_session": {
                "name": "london",
                "start": "2026-03-09T07:00:00+00:00",
                "end": "2026-03-09T12:00:00+00:00",
                "active": true
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
            "regime_label": "range",
            "transition_score": 20.0,
            "transition_state": "none",
            "transition_lock_reason": null,
            "active_thesis_clusters": 9,
            "strategy_mode": "A_ONLY",
            "feature_calibration_available": false,
            "feature_calibration_samples": 0,
            "signal_alerts": {
              "near": 0,
              "touch": 1,
              "confirm": 1,
              "emitted_total": 0
            }
          }
        },
        {
          "symbol": "UNIUSDC",
          "status": "ok",
          "backfill": {
            "1m": 16,
            "5m": 4,
            "15m": 2,
            "total": 22
          },
          "refresh": {
            "symbol": "UNIUSDC",
            "updated": true,
            "zones": 81,
            "plans": 5,
            "risk_state": "OPEN",
            "gate_reason": "normal",
            "operating_lock": {
              "state": "OPEN",
              "active": false,
              "enforced": true,
              "reason": "normal",
              "scope": "none",
              "strategy_mode": "A_ONLY",
              "unlock_at": null,
              "current_session": {
                "name": "london",
                "start": "2026-03-09T07:00:00+00:00",
                "end": "2026-03-09T12:00:00+00:00",
                "active": true
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
            "regime_label": "range",
            "transition_score": 49.0,
            "transition_state": "transition_watch",
            "transition_lock_reason": "transition_score_watch",
            "active_thesis_clusters": 9,
            "strategy_mode": "A_ONLY",
            "feature_calibration_available": false,
            "feature_calibration_samples": 0,
            "signal_alerts": {
              "near": 0,
              "touch": 0,
              "confirm": 0,
              "emitted_total": 0
            }
          }
        },
        {
          "symbol": "WLDUSDC",
          "status": "ok",
          "backfill": {
            "1m": 16,
            "5m": 4,
            "15m": 2,
            "total": 22
          },
          "refresh": {
            "symbol": "WLDUSDC",
            "updated": true,
            "zones": 65,
            "plans": 6,
            "risk_state": "OPEN",
            "gate_reason": "normal",
            "operating_lock": {
              "state": "OPEN",
              "active": false,
              "enforced": true,
              "reason": "normal",
              "scope": "none",
              "strategy_mode": "A_ONLY",
              "unlock_at": null,
              "current_session": {
                "name": "london",
                "start": "2026-03-09T07:00:00+00:00",
                "end": "2026-03-09T12:00:00+00:00",
                "active": true
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
            "regime_label": "range",
            "transition_score": 52.0,
            "transition_state": "transition_watch",
            "transition_lock_reason": "transition_score_watch",
            "active_thesis_clusters": 9,
            "strategy_mode": "A_ONLY",
            "feature_calibration_available": false,
            "feature_calibration_samples": 0,
            "signal_alerts": {
              "near": 0,
              "touch": 0,
              "confirm": 0,
              "emitted_total": 0
            }
          }
        },
        {
          "symbol": "KAITOUSDC",
          "status": "ok",
          "backfill": {
            "1m": 16,
            "5m": 4,
            "15m": 2,
            "total": 22
          },
          "refresh": {
            "symbol": "KAITOUSDC",
            "updated": true,
            "zones": 45,
            "plans": 0,
            "risk_state": "OPEN",
            "gate_reason": "normal",
            "operating_lock": {
              "state": "OPEN",
              "active": false,
              "enforced": true,
              "reason": "normal",
              "scope": "none",
              "strategy_mode": "A_ONLY",
              "unlock_at": null,
              "current_session": {
                "name": "london",
                "start": "2026-03-09T07:00:00+00:00",
                "end": "2026-03-09T12:00:00+00:00",
                "active": true
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
            "regime_label": "transition",
            "transition_score": 49.0,
            "transition_state": "transition_confirmed",
            "transition_lock_reason": "transition_hard_override_state_disagreement",
            "active_thesis_clusters": 9,
            "strategy_mode": "A_ONLY",
            "feature_calibration_available": false,
            "feature_calibration_samples": 0,
            "signal_alerts": {
              "near": 0,
              "touch": 0,
              "confirm": 0,
              "emitted_total": 0
            }
          }
        },
        {
          "symbol": "1000BONKUSDC",
          "status": "ok",
          "backfill": {
            "1m": 16,
            "5m": 4,
            "15m": 2,
            "total": 22
          },
          "refresh": {
            "symbol": "1000BONKUSDC",
            "updated": true,
            "zones": 50,
            "plans": 0,
            "risk_state": "OPEN",
            "gate_reason": "normal",
            "operating_lock": {
              "state": "OPEN",
              "active": false,
              "enforced": true,
              "reason": "normal",
              "scope": "none",
              "strategy_mode": "A_ONLY",
              "unlock_at": null,
              "current_session": {
                "name": "london",
                "start": "2026-03-09T07:00:00+00:00",
                "end": "2026-03-09T12:00:00+00:00",
                "active": true
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
            "regime_label": "transition",
            "transition_score": 67.0,
            "transition_state": "transition_confirmed",
            "transition_lock_reason": "transition_hard_override_information_failure",
            "active_thesis_clusters": 9,
            "strategy_mode": "A_ONLY",
            "feature_calibration_available": false,
            "feature_calibration_samples": 0,
            "signal_alerts": {
              "near": 1,
              "touch": 0,
              "confirm": 0,
              "emitted_total": 0
            }
          }
        },
        {
          "symbol": "PENGUUSDC",
          "status": "ok",
          "backfill": {
            "1m": 16,
            "5m": 4,
            "15m": 2,
            "total": 22
          },
          "refresh": {
            "symbol": "PENGUUSDC",
            "updated": true,
            "zones": 73,
            "plans": 5,
            "risk_state": "OPEN",
            "gate_reason": "normal",
            "operating_lock": {
              "state": "OPEN",
              "active": false,
              "enforced": true,
              "reason": "normal",
              "scope": "none",
              "strategy_mode": "A_ONLY",
              "unlock_at": null,
              "current_session": {
                "name": "london",
                "start": "2026-03-09T07:00:00+00:00",
                "end": "2026-03-09T12:00:00+00:00",
                "active": true
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
            "regime_label": "range",
            "transition_score": 34.0,
            "transition_state": "none",
            "transition_lock_reason": null,
            "active_thesis_clusters": 9,
            "strategy_mode": "A_ONLY",
            "feature_calibration_available": false,
            "feature_calibration_samples": 0,
            "signal_alerts": {
              "near": 0,
              "touch": 0,
              "confirm": 0,
              "emitted_total": 0
            }
          }
        },
        {
          "symbol": "TIAUSDC",
          "status": "ok",
          "backfill": {
            "1m": 16,
            "5m": 4,
            "15m": 2,
            "total": 22
          },
          "refresh": {
            "symbol": "TIAUSDC",
            "updated": true,
            "zones": 80,
            "plans": 3,
            "risk_state": "OPEN",
            "gate_reason": "normal",
            "operating_lock": {
              "state": "OPEN",
              "active": false,
              "enforced": true,
              "reason": "normal",
              "scope": "none",
              "strategy_mode": "A_ONLY",
              "unlock_at": null,
              "current_session": {
                "name": "london",
                "start": "2026-03-09T07:00:00+00:00",
                "end": "2026-03-09T12:00:00+00:00",
                "active": true
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
            "regime_label": "range",
            "transition_score": 49.0,
            "transition_state": "transition_watch",
            "transition_lock_reason": "transition_score_watch",
            "active_thesis_clusters": 9,
            "strategy_mode": "A_ONLY",
            "feature_calibration_available": false,
            "feature_calibration_samples": 0,
            "signal_alerts": {
              "near": 0,
              "touch": 0,
              "confirm": 0,
              "emitted_total": 0
            }
          }
        },
        {
          "symbol": "TRUMPUSDC",
          "status": "ok",
          "backfill": {
            "1m": 16,
            "5m": 4,
            "15m": 2,
            "total": 22
          },
          "refresh": {
            "symbol": "TRUMPUSDC",
            "updated": true,
            "zones": 75,
            "plans": 3,
            "risk_state": "OPEN",
            "gate_reason": "normal",
            "operating_lock": {
              "state": "OPEN",
              "active": false,
              "enforced": true,
              "reason": "normal",
              "scope": "none",
              "strategy_mode": "A_ONLY",
              "unlock_at": null,
              "current_session": {
                "name": "london",
                "start": "2026-03-09T07:00:00+00:00",
                "end": "2026-03-09T12:00:00+00:00",
                "active": true
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
            "regime_label": "range",
            "transition_score": 53.0,
            "transition_state": "transition_watch",
            "transition_lock_reason": "transition_score_watch",
            "active_thesis_clusters": 9,
            "strategy_mode": "A_ONLY",
            "feature_calibration_available": false,
            "feature_calibration_samples": 0,
            "signal_alerts": {
              "near": 1,
              "touch": 0,
              "confirm": 0,
              "emitted_total": 0
            }
          }
        }
      ]
    },
    "portfolio": null,
    "candidate": null,
    "preview": null,
    "approval": null,
    "intent": null,
    "submission": null,
    "next_steps": [
      "Wait for London/New York session and rerun this helper until an eligible family candidate appears.",
      "Keep focus on trend_continuation or sweep_reversal families; legacy_zone_plan does not advance MICRO_LIVE lineage.",
      "No PAPER submission occurred in this run."
    ],
    "_return_code": 1,
    "_stderr": ""
  },
  "next_steps": [
    "Rerun this watcher during London/New York preferred sessions.",
    "Keep focus on trend_continuation or sweep_reversal families; legacy_zone_plan does not advance MICRO_LIVE lineage.",
    "No PAPER lineage submission occurred because no eligible family candidate appeared."
  ]
}
```