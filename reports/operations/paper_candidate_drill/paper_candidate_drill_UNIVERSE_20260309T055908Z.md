# PAPER Candidate Drill

- generated_at: 2026-03-09T05:59:08.845396+00:00
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
  "generated_at": "2026-03-09T05:59:08.845396+00:00",
  "symbol": null,
  "universe": "usdc_perp_top30",
  "families": [
    "sweep_reversal",
    "trend_continuation"
  ],
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
          "1m": 3,
          "5m": 1,
          "15m": 1,
          "total": 5
        },
        "refresh": {
          "symbol": "BTCUSDC",
          "updated": true,
          "zones": 140,
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
              "name": "inactive",
              "start": "2026-03-09T05:59:09.272509+00:00",
              "end": "2026-03-09T05:59:09.272509+00:00",
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
          "regime_label": "range",
          "transition_score": 20.0,
          "transition_state": "none",
          "transition_lock_reason": null,
          "active_thesis_clusters": 6,
          "strategy_mode": "A_ONLY",
          "feature_calibration_available": false,
          "feature_calibration_samples": 0,
          "signal_alerts": {
            "near": 3,
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
          "1m": 2,
          "5m": 1,
          "15m": 1,
          "total": 4
        },
        "refresh": {
          "symbol": "ETHUSDC",
          "updated": true,
          "zones": 69,
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
              "name": "inactive",
              "start": "2026-03-09T05:59:09.240742+00:00",
              "end": "2026-03-09T05:59:09.240742+00:00",
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
          "regime_label": "range",
          "transition_score": 32.0,
          "transition_state": "none",
          "transition_lock_reason": null,
          "active_thesis_clusters": 6,
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
          "1m": 3,
          "5m": 1,
          "15m": 1,
          "total": 5
        },
        "refresh": {
          "symbol": "SOLUSDC",
          "updated": true,
          "zones": 69,
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
              "name": "inactive",
              "start": "2026-03-09T05:59:09.346967+00:00",
              "end": "2026-03-09T05:59:09.346967+00:00",
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
          "regime_label": "range",
          "transition_score": 49.0,
          "transition_state": "transition_watch",
          "transition_lock_reason": "transition_score_watch",
          "active_thesis_clusters": 6,
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
          "1m": 2,
          "5m": 1,
          "15m": 1,
          "total": 4
        },
        "refresh": {
          "symbol": "XRPUSDC",
          "updated": true,
          "zones": 63,
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
              "name": "inactive",
              "start": "2026-03-09T05:59:09.212579+00:00",
              "end": "2026-03-09T05:59:09.212579+00:00",
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
          "regime_label": "range",
          "transition_score": 38.0,
          "transition_state": "none",
          "transition_lock_reason": null,
          "active_thesis_clusters": 6,
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
          "1m": 2,
          "5m": 1,
          "15m": 1,
          "total": 4
        },
        "refresh": {
          "symbol": "BNBUSDC",
          "updated": true,
          "zones": 63,
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
              "name": "inactive",
              "start": "2026-03-09T05:59:09.516699+00:00",
              "end": "2026-03-09T05:59:09.516699+00:00",
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
          "regime_label": "range",
          "transition_score": 15.0,
          "transition_state": "none",
          "transition_lock_reason": null,
          "active_thesis_clusters": 6,
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
        "symbol": "DOGEUSDC",
        "status": "ok",
        "backfill": {
          "1m": 3,
          "5m": 1,
          "15m": 1,
          "total": 5
        },
        "refresh": {
          "symbol": "DOGEUSDC",
          "updated": true,
          "zones": 71,
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
              "name": "inactive",
              "start": "2026-03-09T05:59:09.562156+00:00",
              "end": "2026-03-09T05:59:09.562156+00:00",
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
          "regime_label": "range",
          "transition_score": 38.0,
          "transition_state": "none",
          "transition_lock_reason": null,
          "active_thesis_clusters": 6,
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
          "1m": 3,
          "5m": 1,
          "15m": 1,
          "total": 5
        },
        "refresh": {
          "symbol": "ZECUSDC",
          "updated": true,
          "zones": 82,
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
              "name": "inactive",
              "start": "2026-03-09T05:59:09.562304+00:00",
              "end": "2026-03-09T05:59:09.562304+00:00",
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
          "regime_label": "range",
          "transition_score": 20.0,
          "transition_state": "none",
          "transition_lock_reason": null,
          "active_thesis_clusters": 6,
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
          "1m": 3,
          "5m": 1,
          "15m": 1,
          "total": 5
        },
        "refresh": {
          "symbol": "SUIUSDC",
          "updated": true,
          "zones": 66,
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
              "name": "inactive",
              "start": "2026-03-09T05:59:09.621932+00:00",
              "end": "2026-03-09T05:59:09.621932+00:00",
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
          "regime_label": "range",
          "transition_score": 20.0,
          "transition_state": "none",
          "transition_lock_reason": null,
          "active_thesis_clusters": 6,
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
          "1m": 3,
          "5m": 1,
          "15m": 1,
          "total": 5
        },
        "refresh": {
          "symbol": "1000PEPEUSDC",
          "updated": true,
          "zones": 69,
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
              "name": "inactive",
              "start": "2026-03-09T05:59:09.870328+00:00",
              "end": "2026-03-09T05:59:09.870328+00:00",
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
          "regime_label": "range",
          "transition_score": 20.0,
          "transition_state": "none",
          "transition_lock_reason": null,
          "active_thesis_clusters": 6,
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
          "1m": 3,
          "5m": 1,
          "15m": 1,
          "total": 5
        },
        "refresh": {
          "symbol": "BCHUSDC",
          "updated": true,
          "zones": 61,
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
              "name": "inactive",
              "start": "2026-03-09T05:59:09.855290+00:00",
              "end": "2026-03-09T05:59:09.855290+00:00",
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
          "regime_label": "range",
          "transition_score": 35.0,
          "transition_state": "none",
          "transition_lock_reason": null,
          "active_thesis_clusters": 6,
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
          "1m": 3,
          "5m": 1,
          "15m": 1,
          "total": 5
        },
        "refresh": {
          "symbol": "LINKUSDC",
          "updated": true,
          "zones": 64,
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
              "name": "inactive",
              "start": "2026-03-09T05:59:09.905179+00:00",
              "end": "2026-03-09T05:59:09.905179+00:00",
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
          "regime_label": "range",
          "transition_score": 20.0,
          "transition_state": "none",
          "transition_lock_reason": null,
          "active_thesis_clusters": 6,
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
          "1m": 3,
          "5m": 1,
          "15m": 1,
          "total": 5
        },
        "refresh": {
          "symbol": "ADAUSDC",
          "updated": true,
          "zones": 63,
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
              "name": "inactive",
              "start": "2026-03-09T05:59:09.929763+00:00",
              "end": "2026-03-09T05:59:09.929763+00:00",
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
          "regime_label": "range",
          "transition_score": 20.0,
          "transition_state": "none",
          "transition_lock_reason": null,
          "active_thesis_clusters": 6,
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
          "1m": 3,
          "5m": 1,
          "15m": 1,
          "total": 5
        },
        "refresh": {
          "symbol": "AVAXUSDC",
          "updated": true,
          "zones": 76,
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
              "name": "inactive",
              "start": "2026-03-09T05:59:10.156088+00:00",
              "end": "2026-03-09T05:59:10.156088+00:00",
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
          "regime_label": "range",
          "transition_score": 14.0,
          "transition_state": "none",
          "transition_lock_reason": null,
          "active_thesis_clusters": 6,
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
          "1m": 2,
          "5m": 1,
          "15m": 1,
          "total": 4
        },
        "refresh": {
          "symbol": "LTCUSDC",
          "updated": true,
          "zones": 67,
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
              "name": "inactive",
              "start": "2026-03-09T05:59:10.134511+00:00",
              "end": "2026-03-09T05:59:10.134511+00:00",
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
          "regime_label": "range",
          "transition_score": 34.0,
          "transition_state": "none",
          "transition_lock_reason": null,
          "active_thesis_clusters": 6,
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
          "1m": 3,
          "5m": 1,
          "15m": 1,
          "total": 5
        },
        "refresh": {
          "symbol": "ENAUSDC",
          "updated": true,
          "zones": 83,
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
              "name": "inactive",
              "start": "2026-03-09T05:59:10.188403+00:00",
              "end": "2026-03-09T05:59:10.188403+00:00",
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
          "regime_label": "range",
          "transition_score": 35.0,
          "transition_state": "none",
          "transition_lock_reason": null,
          "active_thesis_clusters": 6,
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
          "1m": 3,
          "5m": 1,
          "15m": 1,
          "total": 5
        },
        "refresh": {
          "symbol": "FILUSDC",
          "updated": true,
          "zones": 75,
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
              "name": "inactive",
              "start": "2026-03-09T05:59:10.289620+00:00",
              "end": "2026-03-09T05:59:10.289620+00:00",
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
          "regime_label": "range",
          "transition_score": 34.0,
          "transition_state": "none",
          "transition_lock_reason": null,
          "active_thesis_clusters": 6,
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
          "1m": 3,
          "5m": 1,
          "15m": 1,
          "total": 5
        },
        "refresh": {
          "symbol": "CRVUSDC",
          "updated": true,
          "zones": 75,
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
              "name": "inactive",
              "start": "2026-03-09T05:59:10.419348+00:00",
              "end": "2026-03-09T05:59:10.419348+00:00",
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
          "regime_label": "range",
          "transition_score": 49.0,
          "transition_state": "transition_watch",
          "transition_lock_reason": "transition_score_watch",
          "active_thesis_clusters": 6,
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
          "1m": 3,
          "5m": 1,
          "15m": 1,
          "total": 5
        },
        "refresh": {
          "symbol": "NEARUSDC",
          "updated": true,
          "zones": 52,
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
              "name": "inactive",
              "start": "2026-03-09T05:59:10.518588+00:00",
              "end": "2026-03-09T05:59:10.518588+00:00",
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
          "regime_label": "range",
          "transition_score": 35.0,
          "transition_state": "none",
          "transition_lock_reason": null,
          "active_thesis_clusters": 6,
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
          "1m": 3,
          "5m": 1,
          "15m": 1,
          "total": 5
        },
        "refresh": {
          "symbol": "ARBUSDC",
          "updated": true,
          "zones": 70,
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
              "name": "inactive",
              "start": "2026-03-09T05:59:10.470281+00:00",
              "end": "2026-03-09T05:59:10.470281+00:00",
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
          "regime_label": "range",
          "transition_score": 20.0,
          "transition_state": "none",
          "transition_lock_reason": null,
          "active_thesis_clusters": 6,
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
          "1m": 3,
          "5m": 1,
          "15m": 1,
          "total": 5
        },
        "refresh": {
          "symbol": "WIFUSDC",
          "updated": true,
          "zones": 73,
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
              "name": "inactive",
              "start": "2026-03-09T05:59:10.593322+00:00",
              "end": "2026-03-09T05:59:10.593322+00:00",
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
          "regime_label": "range",
          "transition_score": 0.0,
          "transition_state": "none",
          "transition_lock_reason": null,
          "active_thesis_clusters": 6,
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
          "1m": 3,
          "5m": 1,
          "15m": 1,
          "total": 5
        },
        "refresh": {
          "symbol": "AAVEUSDC",
          "updated": true,
          "zones": 66,
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
              "name": "inactive",
              "start": "2026-03-09T05:59:10.719437+00:00",
              "end": "2026-03-09T05:59:10.719437+00:00",
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
          "regime_label": "range",
          "transition_score": 38.0,
          "transition_state": "none",
          "transition_lock_reason": null,
          "active_thesis_clusters": 6,
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
          "1m": 3,
          "5m": 1,
          "15m": 1,
          "total": 5
        },
        "refresh": {
          "symbol": "IPUSDC",
          "updated": true,
          "zones": 80,
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
              "name": "inactive",
              "start": "2026-03-09T05:59:10.803528+00:00",
              "end": "2026-03-09T05:59:10.803528+00:00",
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
          "regime_label": "range",
          "transition_score": 29.0,
          "transition_state": "none",
          "transition_lock_reason": null,
          "active_thesis_clusters": 6,
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
          "1m": 3,
          "5m": 1,
          "15m": 1,
          "total": 5
        },
        "refresh": {
          "symbol": "WLFIUSDC",
          "updated": true,
          "zones": 46,
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
              "name": "inactive",
              "start": "2026-03-09T05:59:10.777487+00:00",
              "end": "2026-03-09T05:59:10.777487+00:00",
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
          "regime_label": "range",
          "transition_score": 0.0,
          "transition_state": "none",
          "transition_lock_reason": null,
          "active_thesis_clusters": 6,
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
        "symbol": "WLDUSDC",
        "status": "ok",
        "backfill": {
          "1m": 3,
          "5m": 1,
          "15m": 1,
          "total": 5
        },
        "refresh": {
          "symbol": "WLDUSDC",
          "updated": true,
          "zones": 60,
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
              "name": "inactive",
              "start": "2026-03-09T05:59:10.885711+00:00",
              "end": "2026-03-09T05:59:10.885711+00:00",
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
          "regime_label": "range",
          "transition_score": 53.0,
          "transition_state": "transition_watch",
          "transition_lock_reason": "transition_score_watch",
          "active_thesis_clusters": 6,
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
          "1m": 3,
          "5m": 1,
          "15m": 1,
          "total": 5
        },
        "refresh": {
          "symbol": "KAITOUSDC",
          "updated": true,
          "zones": 40,
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
              "name": "inactive",
              "start": "2026-03-09T05:59:11.007840+00:00",
              "end": "2026-03-09T05:59:11.007840+00:00",
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
          "regime_label": "range",
          "transition_score": 14.0,
          "transition_state": "none",
          "transition_lock_reason": null,
          "active_thesis_clusters": 6,
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
          "1m": 3,
          "5m": 1,
          "15m": 1,
          "total": 5
        },
        "refresh": {
          "symbol": "UNIUSDC",
          "updated": true,
          "zones": 72,
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
              "name": "inactive",
              "start": "2026-03-09T05:59:11.077660+00:00",
              "end": "2026-03-09T05:59:11.077660+00:00",
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
          "regime_label": "range",
          "transition_score": 14.0,
          "transition_state": "none",
          "transition_lock_reason": null,
          "active_thesis_clusters": 6,
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
        "symbol": "1000BONKUSDC",
        "status": "ok",
        "backfill": {
          "1m": 3,
          "5m": 1,
          "15m": 1,
          "total": 5
        },
        "refresh": {
          "symbol": "1000BONKUSDC",
          "updated": true,
          "zones": 27,
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
              "name": "inactive",
              "start": "2026-03-09T05:59:11.109805+00:00",
              "end": "2026-03-09T05:59:11.109805+00:00",
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
          "regime_label": "range",
          "transition_score": 0.0,
          "transition_state": "none",
          "transition_lock_reason": null,
          "active_thesis_clusters": 6,
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
        "symbol": "PENGUUSDC",
        "status": "ok",
        "backfill": {
          "1m": 3,
          "5m": 1,
          "15m": 1,
          "total": 5
        },
        "refresh": {
          "symbol": "PENGUUSDC",
          "updated": true,
          "zones": 70,
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
              "name": "inactive",
              "start": "2026-03-09T05:59:11.144779+00:00",
              "end": "2026-03-09T05:59:11.144779+00:00",
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
          "regime_label": "range",
          "transition_score": 20.0,
          "transition_state": "none",
          "transition_lock_reason": null,
          "active_thesis_clusters": 6,
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
          "1m": 3,
          "5m": 1,
          "15m": 1,
          "total": 5
        },
        "refresh": {
          "symbol": "TIAUSDC",
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
              "name": "inactive",
              "start": "2026-03-09T05:59:11.259105+00:00",
              "end": "2026-03-09T05:59:11.259105+00:00",
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
          "regime_label": "range",
          "transition_score": 20.0,
          "transition_state": "none",
          "transition_lock_reason": null,
          "active_thesis_clusters": 6,
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
        "symbol": "TRUMPUSDC",
        "status": "ok",
        "backfill": {
          "1m": 3,
          "5m": 1,
          "15m": 1,
          "total": 5
        },
        "refresh": {
          "symbol": "TRUMPUSDC",
          "updated": true,
          "zones": 64,
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
              "name": "inactive",
              "start": "2026-03-09T05:59:11.353956+00:00",
              "end": "2026-03-09T05:59:11.353956+00:00",
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
          "regime_label": "range",
          "transition_score": 35.0,
          "transition_state": "none",
          "transition_lock_reason": null,
          "active_thesis_clusters": 6,
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
      }
    ]
  },
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