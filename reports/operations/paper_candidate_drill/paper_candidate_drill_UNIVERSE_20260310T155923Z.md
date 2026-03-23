# PAPER Candidate Drill

- generated_at: 2026-03-10T15:59:23.271393+00:00
- overall_status: NOT_READY
- summary: 1 blocking drill check(s) remain.

## Checks

- [PASS] universe_sync: success=30 failed=0 processed=30
- [FAIL] eligible_candidate_found: No eligible trend_continuation/sweep_reversal candidate found in scanner output.

## Candidate

- no eligible candidate found

## Next Steps

- Wait for London/New York session and rerun this helper until an eligible family candidate appears.
- Keep focus on trend_continuation or sweep_reversal families; legacy_zone_plan does not advance MICRO_LIVE lineage.
- No PAPER submission occurred in this run.

## Raw Payload

```json
{
  "generated_at": "2026-03-10T15:59:23.271393+00:00",
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
          "1m": 1,
          "5m": 1,
          "15m": 1,
          "total": 3
        },
        "refresh": {
          "symbol": "BTCUSDC",
          "updated": true,
          "zones": 28,
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
              "name": "new_york",
              "start": "2026-03-10T13:00:00+00:00",
              "end": "2026-03-10T18:00:00+00:00",
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
          "transition_score": 52.0,
          "transition_state": "transition_confirmed",
          "transition_lock_reason": "transition_hard_override_mixed_sweep",
          "active_thesis_clusters": 5,
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
          "1m": 1,
          "5m": 1,
          "15m": 1,
          "total": 3
        },
        "refresh": {
          "symbol": "ETHUSDC",
          "updated": true,
          "zones": 23,
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
              "name": "new_york",
              "start": "2026-03-10T13:00:00+00:00",
              "end": "2026-03-10T18:00:00+00:00",
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
          "active_thesis_clusters": 5,
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
          "1m": 1,
          "5m": 1,
          "15m": 1,
          "total": 3
        },
        "refresh": {
          "symbol": "SOLUSDC",
          "updated": true,
          "zones": 26,
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
              "name": "new_york",
              "start": "2026-03-10T13:00:00+00:00",
              "end": "2026-03-10T18:00:00+00:00",
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
          "transition_score": 52.0,
          "transition_state": "transition_confirmed",
          "transition_lock_reason": "transition_hard_override_mixed_sweep",
          "active_thesis_clusters": 5,
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
        "symbol": "XRPUSDC",
        "status": "ok",
        "backfill": {
          "1m": 1,
          "5m": 1,
          "15m": 1,
          "total": 3
        },
        "refresh": {
          "symbol": "XRPUSDC",
          "updated": true,
          "zones": 20,
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
              "name": "new_york",
              "start": "2026-03-10T13:00:00+00:00",
              "end": "2026-03-10T18:00:00+00:00",
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
          "transition_lock_reason": "transition_hard_override_mixed_sweep",
          "active_thesis_clusters": 5,
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
          "1m": 1,
          "5m": 1,
          "15m": 1,
          "total": 3
        },
        "refresh": {
          "symbol": "BNBUSDC",
          "updated": true,
          "zones": 35,
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
              "name": "new_york",
              "start": "2026-03-10T13:00:00+00:00",
              "end": "2026-03-10T18:00:00+00:00",
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
          "active_thesis_clusters": 5,
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
          "1m": 1,
          "5m": 1,
          "15m": 1,
          "total": 3
        },
        "refresh": {
          "symbol": "DOGEUSDC",
          "updated": true,
          "zones": 12,
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
              "name": "new_york",
              "start": "2026-03-10T13:00:00+00:00",
              "end": "2026-03-10T18:00:00+00:00",
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
          "active_thesis_clusters": 5,
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
          "1m": 1,
          "5m": 1,
          "15m": 1,
          "total": 3
        },
        "refresh": {
          "symbol": "ZECUSDC",
          "updated": true,
          "zones": 28,
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
              "name": "new_york",
              "start": "2026-03-10T13:00:00+00:00",
              "end": "2026-03-10T18:00:00+00:00",
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
          "active_thesis_clusters": 5,
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
          "1m": 1,
          "5m": 1,
          "15m": 1,
          "total": 3
        },
        "refresh": {
          "symbol": "SUIUSDC",
          "updated": true,
          "zones": 23,
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
              "name": "new_york",
              "start": "2026-03-10T13:00:00+00:00",
              "end": "2026-03-10T18:00:00+00:00",
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
          "active_thesis_clusters": 5,
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
          "1m": 1,
          "5m": 1,
          "15m": 1,
          "total": 3
        },
        "refresh": {
          "symbol": "ADAUSDC",
          "updated": true,
          "zones": 19,
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
              "name": "new_york",
              "start": "2026-03-10T13:00:00+00:00",
              "end": "2026-03-10T18:00:00+00:00",
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
          "active_thesis_clusters": 5,
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
          "1m": 1,
          "5m": 1,
          "15m": 1,
          "total": 3
        },
        "refresh": {
          "symbol": "1000PEPEUSDC",
          "updated": true,
          "zones": 18,
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
              "name": "new_york",
              "start": "2026-03-10T13:00:00+00:00",
              "end": "2026-03-10T18:00:00+00:00",
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
          "active_thesis_clusters": 5,
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
        "symbol": "BCHUSDC",
        "status": "ok",
        "backfill": {
          "1m": 1,
          "5m": 1,
          "15m": 1,
          "total": 3
        },
        "refresh": {
          "symbol": "BCHUSDC",
          "updated": true,
          "zones": 22,
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
              "name": "new_york",
              "start": "2026-03-10T13:00:00+00:00",
              "end": "2026-03-10T18:00:00+00:00",
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
          "active_thesis_clusters": 5,
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
          "1m": 1,
          "5m": 1,
          "15m": 1,
          "total": 3
        },
        "refresh": {
          "symbol": "LINKUSDC",
          "updated": true,
          "zones": 25,
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
              "name": "new_york",
              "start": "2026-03-10T13:00:00+00:00",
              "end": "2026-03-10T18:00:00+00:00",
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
          "active_thesis_clusters": 5,
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
          "1m": 1,
          "5m": 1,
          "15m": 1,
          "total": 3
        },
        "refresh": {
          "symbol": "AVAXUSDC",
          "updated": true,
          "zones": 30,
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
              "name": "new_york",
              "start": "2026-03-10T13:00:00+00:00",
              "end": "2026-03-10T18:00:00+00:00",
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
          "active_thesis_clusters": 5,
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
          "1m": 1,
          "5m": 1,
          "15m": 1,
          "total": 3
        },
        "refresh": {
          "symbol": "ENAUSDC",
          "updated": true,
          "zones": 21,
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
              "name": "new_york",
              "start": "2026-03-10T13:00:00+00:00",
              "end": "2026-03-10T18:00:00+00:00",
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
          "active_thesis_clusters": 5,
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
          "1m": 1,
          "5m": 1,
          "15m": 1,
          "total": 3
        },
        "refresh": {
          "symbol": "LTCUSDC",
          "updated": true,
          "zones": 24,
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
              "name": "new_york",
              "start": "2026-03-10T13:00:00+00:00",
              "end": "2026-03-10T18:00:00+00:00",
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
          "active_thesis_clusters": 5,
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
        "symbol": "NEARUSDC",
        "status": "ok",
        "backfill": {
          "1m": 1,
          "5m": 1,
          "15m": 1,
          "total": 3
        },
        "refresh": {
          "symbol": "NEARUSDC",
          "updated": true,
          "zones": 30,
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
              "name": "new_york",
              "start": "2026-03-10T13:00:00+00:00",
              "end": "2026-03-10T18:00:00+00:00",
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
          "transition_score": 14.0,
          "transition_state": "none",
          "transition_lock_reason": null,
          "active_thesis_clusters": 5,
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
          "1m": 1,
          "5m": 1,
          "15m": 1,
          "total": 3
        },
        "refresh": {
          "symbol": "CRVUSDC",
          "updated": true,
          "zones": 36,
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
              "name": "new_york",
              "start": "2026-03-10T13:00:00+00:00",
              "end": "2026-03-10T18:00:00+00:00",
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
          "transition_score": 38.0,
          "transition_state": "none",
          "transition_lock_reason": null,
          "active_thesis_clusters": 5,
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
        "symbol": "FILUSDC",
        "status": "ok",
        "backfill": {
          "1m": 1,
          "5m": 1,
          "15m": 1,
          "total": 3
        },
        "refresh": {
          "symbol": "FILUSDC",
          "updated": true,
          "zones": 21,
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
              "name": "new_york",
              "start": "2026-03-10T13:00:00+00:00",
              "end": "2026-03-10T18:00:00+00:00",
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
          "transition_score": 38.0,
          "transition_state": "none",
          "transition_lock_reason": null,
          "active_thesis_clusters": 5,
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
          "1m": 1,
          "5m": 1,
          "15m": 1,
          "total": 3
        },
        "refresh": {
          "symbol": "WIFUSDC",
          "updated": true,
          "zones": 23,
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
              "name": "new_york",
              "start": "2026-03-10T13:00:00+00:00",
              "end": "2026-03-10T18:00:00+00:00",
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
          "transition_score": 85.0,
          "transition_state": "transition_confirmed",
          "transition_lock_reason": "transition_hard_override_mixed_sweep",
          "active_thesis_clusters": 5,
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
          "1m": 1,
          "5m": 1,
          "15m": 1,
          "total": 3
        },
        "refresh": {
          "symbol": "AAVEUSDC",
          "updated": true,
          "zones": 18,
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
              "name": "new_york",
              "start": "2026-03-10T13:00:00+00:00",
              "end": "2026-03-10T18:00:00+00:00",
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
          "transition_score": 52.0,
          "transition_state": "transition_confirmed",
          "transition_lock_reason": "transition_hard_override_mixed_sweep",
          "active_thesis_clusters": 5,
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
        "symbol": "1000SHIBUSDC",
        "status": "ok",
        "backfill": {
          "1m": 1,
          "5m": 1,
          "15m": 1,
          "total": 3
        },
        "refresh": {
          "symbol": "1000SHIBUSDC",
          "updated": true,
          "zones": 15,
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
              "name": "new_york",
              "start": "2026-03-10T13:00:00+00:00",
              "end": "2026-03-10T18:00:00+00:00",
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
          "active_thesis_clusters": 5,
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
        "symbol": "ARBUSDC",
        "status": "ok",
        "backfill": {
          "1m": 1,
          "5m": 1,
          "15m": 1,
          "total": 3
        },
        "refresh": {
          "symbol": "ARBUSDC",
          "updated": true,
          "zones": 30,
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
              "name": "new_york",
              "start": "2026-03-10T13:00:00+00:00",
              "end": "2026-03-10T18:00:00+00:00",
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
          "active_thesis_clusters": 5,
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
        "symbol": "PENGUUSDC",
        "status": "ok",
        "backfill": {
          "1m": 1,
          "5m": 1,
          "15m": 1,
          "total": 3
        },
        "refresh": {
          "symbol": "PENGUUSDC",
          "updated": true,
          "zones": 23,
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
              "name": "new_york",
              "start": "2026-03-10T13:00:00+00:00",
              "end": "2026-03-10T18:00:00+00:00",
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
          "active_thesis_clusters": 5,
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
          "1m": 1,
          "5m": 1,
          "15m": 1,
          "total": 3
        },
        "refresh": {
          "symbol": "WLDUSDC",
          "updated": true,
          "zones": 21,
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
              "name": "new_york",
              "start": "2026-03-10T13:00:00+00:00",
              "end": "2026-03-10T18:00:00+00:00",
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
          "transition_score": 38.0,
          "transition_state": "none",
          "transition_lock_reason": null,
          "active_thesis_clusters": 5,
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
        "symbol": "HBARUSDC",
        "status": "ok",
        "backfill": {
          "1m": 1,
          "5m": 1,
          "15m": 1,
          "total": 3
        },
        "refresh": {
          "symbol": "HBARUSDC",
          "updated": true,
          "zones": 19,
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
              "name": "new_york",
              "start": "2026-03-10T13:00:00+00:00",
              "end": "2026-03-10T18:00:00+00:00",
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
          "active_thesis_clusters": 5,
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
        "symbol": "TIAUSDC",
        "status": "ok",
        "backfill": {
          "1m": 1,
          "5m": 1,
          "15m": 1,
          "total": 3
        },
        "refresh": {
          "symbol": "TIAUSDC",
          "updated": true,
          "zones": 23,
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
              "name": "new_york",
              "start": "2026-03-10T13:00:00+00:00",
              "end": "2026-03-10T18:00:00+00:00",
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
          "active_thesis_clusters": 5,
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
        "symbol": "IPUSDC",
        "status": "ok",
        "backfill": {
          "1m": 1,
          "5m": 1,
          "15m": 1,
          "total": 3
        },
        "refresh": {
          "symbol": "IPUSDC",
          "updated": true,
          "zones": 32,
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
              "name": "new_york",
              "start": "2026-03-10T13:00:00+00:00",
              "end": "2026-03-10T18:00:00+00:00",
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
          "active_thesis_clusters": 5,
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
          "1m": 1,
          "5m": 1,
          "15m": 1,
          "total": 3
        },
        "refresh": {
          "symbol": "1000BONKUSDC",
          "updated": true,
          "zones": 21,
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
              "name": "new_york",
              "start": "2026-03-10T13:00:00+00:00",
              "end": "2026-03-10T18:00:00+00:00",
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
          "transition_lock_reason": "transition_hard_override_mixed_sweep",
          "active_thesis_clusters": 5,
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
          "1m": 1,
          "5m": 1,
          "15m": 1,
          "total": 3
        },
        "refresh": {
          "symbol": "TRUMPUSDC",
          "updated": true,
          "zones": 24,
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
              "name": "new_york",
              "start": "2026-03-10T13:00:00+00:00",
              "end": "2026-03-10T18:00:00+00:00",
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
          "active_thesis_clusters": 5,
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
        "symbol": "UNIUSDC",
        "status": "ok",
        "backfill": {
          "1m": 1,
          "5m": 1,
          "15m": 1,
          "total": 3
        },
        "refresh": {
          "symbol": "UNIUSDC",
          "updated": true,
          "zones": 28,
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
              "name": "new_york",
              "start": "2026-03-10T13:00:00+00:00",
              "end": "2026-03-10T18:00:00+00:00",
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
          "active_thesis_clusters": 5,
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
  ]
}
```