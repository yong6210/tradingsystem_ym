from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from scripts import install_micro_live_ops_launchd
from scripts import build_micro_live_event_blackouts
from scripts import run_binance_rule_drift_snapshot
from scripts import run_live_reconciliation_watchdog
from scripts import run_live_replay_parity_audit
from scripts import run_replay_validation_bridge
from scripts import run_micro_live_boot_check
from scripts import run_micro_live_no_order_watchdog
from scripts import run_micro_live_ops_heartbeat
from scripts import run_micro_live_runtime_guard
from scripts import run_micro_live_synthetic_canary


def test_no_order_watchdog_alerts_when_live_intents_have_no_submission() -> None:
    lifecycle = {
        "summary": {
            "submission_count": 0,
            "requested_live_count": 0,
            "rejected_or_error_count": 0,
            "live_intents": {
                "total": 3,
                "submit_ready": 0,
                "blocked": 3,
                "top_block_reasons": {"validation_do_not_deploy": 2, "rollout_session_not_allowed": 1},
                "recent_blocked_intents": [
                    {
                        "intent_id": "intent_1",
                        "symbol": "BTCUSDC",
                        "decision_reason_code": "validation_do_not_deploy",
                    },
                    {
                        "intent_id": "intent_2",
                        "symbol": "SOLUSDC",
                        "decision_reason_code": "rollout_session_not_allowed",
                    },
                ],
            },
        }
    }

    result = run_micro_live_no_order_watchdog.evaluate_no_order_watchdog(lifecycle=lifecycle, min_intents=1)

    assert result["alert"] is True
    assert result["reason"] == "live_intents_without_live_order_submission"
    assert "validation_do_not_deploy=2" in result["message"]
    assert "validation_do_not_deploy->inspect_validation_report_approval_surface" in result["message"]
    assert result["blocked_intent_diagnostics"][0]["recent_samples"][0]["intent_id"] == "intent_1"


def test_no_order_watchdog_notification_message_is_concise() -> None:
    message = run_micro_live_no_order_watchdog._watchdog_message(
        {
            "window_days": 3,
            "evaluation": {
                "intent_count": 11,
                "requested_live_count": 0,
                "top_block_reasons": {"validation_do_not_deploy": 9, "rollout_session_not_allowed": 2},
                "first_block_detail_text": "cause=validation_sample_missing, grade=F",
                "blocked_intent_diagnostics": [
                    {
                        "reason": "validation_do_not_deploy",
                        "action": "inspect_validation_report_approval_surface",
                    }
                ],
            },
        }
    )

    assert "MICRO_LIVE 주문 없음" in message
    assert "최근 3일: intent 11건 / 제출 0건" in message
    assert "원인: validation_do_not_deploy=9" in message
    assert "상세: cause=validation_sample_missing, grade=F" in message


def test_no_order_watchdog_main_writes_latest_aliases(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(
        run_micro_live_no_order_watchdog,
        "build_payload",
        lambda **_kwargs: {
            "generated_at": "2026-05-10T00:00:00Z",
            "window_days": 3,
            "min_intents": 1,
            "evaluation": {"alert": False, "status": "OK", "severity": "INFO", "reason": "no_recent_live_intents"},
            "lifecycle_summary": {},
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_micro_live_no_order_watchdog.py",
            "--report-dir",
            str(tmp_path),
            "--no-fail-exit",
        ],
    )

    assert run_micro_live_no_order_watchdog.main() == 0
    output = json.loads(capsys.readouterr().out)

    assert (tmp_path / "micro_live_no_order_watchdog_20260510T000000Z.md").exists()
    assert (tmp_path / "latest.md").exists()
    assert (tmp_path / "latest.json").exists()
    assert output["latest_report_path"].endswith("latest.md")
    latest_payload = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest_payload["evaluation"]["status"] == "OK"


def test_no_order_watchdog_main_does_not_record_cooldown_when_delivery_fails(monkeypatch, tmp_path, capsys) -> None:
    state_file = tmp_path / "state.json"

    class FakeDispatcher:
        def __init__(self, _settings) -> None:
            pass

        def dispatch(self, **_kwargs):
            return {"delivered": False, "skipped": True, "reason": "discord_not_configured"}

    monkeypatch.setattr(
        run_micro_live_no_order_watchdog,
        "build_payload",
        lambda **_kwargs: {
            "generated_at": "2026-05-10T00:00:00Z",
            "window_days": 3,
            "min_intents": 1,
            "evaluation": {
                "alert": True,
                "status": "ALERT",
                "severity": "WARN",
                "reason": "live_intents_without_live_order_submission",
                "top_block_reasons": {"validation_do_not_deploy": 1},
                "blocked_intent_diagnostics": [],
                "intent_count": 1,
                "requested_live_count": 0,
            },
            "lifecycle_summary": {},
        },
    )
    monkeypatch.setattr(run_micro_live_no_order_watchdog, "NotificationDispatcher", FakeDispatcher)
    monkeypatch.setattr(run_micro_live_no_order_watchdog, "get_settings", lambda: object())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_micro_live_no_order_watchdog.py",
            "--notify",
            "--state-file",
            str(state_file),
            "--no-write-report",
            "--no-fail-exit",
        ],
    )

    assert run_micro_live_no_order_watchdog.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["notification"]["reason"] == "discord_not_configured"
    assert output["notification_state"]["reason"] == "delivery_not_confirmed"
    assert not state_file.exists()


def test_synthetic_canary_passes_with_no_network_and_valid_settings(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "auto_trading_live_sizing_mode", "RISK_PCT")
    monkeypatch.setattr(settings, "auto_trading_live_account_equity_usdt", 200.0)
    monkeypatch.setattr(settings, "auto_trading_live_risk_per_trade_pct", 0.01)
    monkeypatch.setattr(settings, "auto_trading_live_usable_margin_fraction", 0.85)
    monkeypatch.setattr(settings, "auto_trading_live_leverage_cap", 10.0)
    monkeypatch.setattr(settings, "auto_trading_live_liquidity_gate_enabled", True)
    monkeypatch.setattr(settings, "auto_trading_live_liquidity_gate_fail_closed", True)
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_symbols", "BTCUSDC")
    monkeypatch.setattr(
        run_micro_live_synthetic_canary,
        "_micro_live_config_drift_checks",
        lambda **_kwargs: [{"name": "config", "status": "PASS", "severity": "blocking", "message": "ok"}],
    )

    payload = run_micro_live_synthetic_canary.run_canary(
        symbol="BTCUSDC",
        direction="long",
        entry_model="LIMIT",
        entry_price=100.0,
        stop_bps=100.0,
        use_network=False,
    )

    assert payload["overall_status"] == "PASS"
    assert payload["no_live_order_sent"] is True
    assert payload["live_sizing"]["normalized_quantity"] > 0


def test_runtime_guard_main_writes_latest_aliases(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(
        run_micro_live_runtime_guard,
        "build_payload",
        lambda **_kwargs: {
            "generated_at": "2026-05-10T00:00:00Z",
            "overall_status": "PASS",
            "operational_status": "PASS",
            "blocking_failures": [],
            "checks": [],
            "lifecycle": {"summary": {"live_intents": {}}},
            "blocked_intent_diagnostics": [],
            "recommendations": [],
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_micro_live_runtime_guard.py",
            "--report-dir",
            str(tmp_path),
            "--no-fail-exit",
        ],
    )

    assert run_micro_live_runtime_guard.main() == 0
    output = json.loads(capsys.readouterr().out)

    assert (tmp_path / "micro_live_runtime_guard_20260510T000000Z.md").exists()
    assert (tmp_path / "latest.md").exists()
    assert (tmp_path / "latest.json").exists()
    assert output["latest_report_path"].endswith("latest.md")
    latest_payload = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest_payload["overall_status"] == "PASS"


def test_synthetic_canary_main_writes_latest_aliases(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(
        run_micro_live_synthetic_canary,
        "run_canary",
        lambda **_kwargs: {
            "generated_at": "2026-05-10T00:00:00Z",
            "overall_status": "PASS",
            "no_live_order_sent": True,
            "symbol": "BTCUSDC",
            "checks": [],
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_micro_live_synthetic_canary.py",
            "--report-dir",
            str(tmp_path),
            "--no-network",
            "--no-fail-exit",
        ],
    )

    assert run_micro_live_synthetic_canary.main() == 0
    output = json.loads(capsys.readouterr().out)

    assert (tmp_path / "micro_live_synthetic_canary_BTCUSDC_20260510T000000Z.md").exists()
    assert (tmp_path / "latest.md").exists()
    assert (tmp_path / "latest.json").exists()
    assert output["latest_report_path"].endswith("latest.md")
    latest_payload = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest_payload["no_live_order_sent"] is True


def test_event_blackout_parsers_extract_official_calendar_rows() -> None:
    fomc_html = """
    <h4>2026 FOMC Meetings</h4>
    <p>June</p><p>16-17*</p>
    <p>July</p><p>28-29</p>
    <h4>2025 FOMC Meetings</h4>
    """
    bls_html = """
    Reference Month Release Date Release Time
    April 2026 May 12, 2026 08:30 AM
    May 2026 Jun. 10, 2026 08:30 AM
    """

    fomc = build_micro_live_event_blackouts.parse_fomc_events(fomc_html, years={2026})
    cpi = build_micro_live_event_blackouts.parse_bls_release_events(
        bls_html,
        code="CPI",
        years={2026},
        source="sample",
    )

    assert [row["label"] for row in fomc] == ["FOMC_2026_06_17", "FOMC_2026_07_29"]
    assert [row["label"] for row in cpi] == ["CPI_2026_05_12", "CPI_2026_06_10"]


def test_event_blackout_bls_ics_parser_extracts_cpi_and_nfp_rows() -> None:
    ics = """
BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART;TZID=US-Eastern:20260512T083000
SUMMARY:Consumer Price Index
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=US-Eastern:20260605T083000
SUMMARY:Employment Situation
END:VEVENT
END:VCALENDAR
"""

    cpi = build_micro_live_event_blackouts.parse_bls_ics_events(ics, code="CPI", years={2026})
    nfp = build_micro_live_event_blackouts.parse_bls_ics_events(ics, code="NFP", years={2026})

    assert [row["label"] for row in cpi] == ["CPI_2026_05_12"]
    assert [row["label"] for row in nfp] == ["NFP_2026_06_05"]


def test_event_blackout_builder_uses_fallback_when_bls_sources_block(monkeypatch, tmp_path) -> None:
    fallback_path = tmp_path / "blackouts.json"
    fallback_path.write_text(
        """
{
  "windows": [
    {"label": "CPI_2026_05_12", "start_utc": "2026-05-12T12:15:00Z", "end_utc": "2026-05-12T13:00:00Z"},
    {"label": "NFP_2026_06_05", "start_utc": "2026-06-05T12:15:00Z", "end_utc": "2026-06-05T13:00:00Z"}
  ]
}
""",
        encoding="utf-8",
    )

    def fake_fetch(url: str) -> str:
        if url == build_micro_live_event_blackouts.FED_FOMC_URL:
            return "<h4>2026 FOMC Meetings</h4><p>June</p><p>16-17</p>"
        raise RuntimeError("blocked")

    monkeypatch.setattr(build_micro_live_event_blackouts, "_fetch_text", fake_fetch)

    payload = build_micro_live_event_blackouts.build_contract(
        years={2026},
        symbols=["BTCUSDC"],
        families=["session_impulse_retest"],
        entry_models=["LIMIT"],
        pre_minutes=15,
        post_minutes=30,
        fallback_input=str(fallback_path),
    )

    assert payload["overall_status"] == "PASS_WITH_WARNINGS"
    assert payload["source_errors"] == []
    assert payload["fallback_window_count"] == 2
    assert [row["label"] for row in payload["windows"]] == [
        "CPI_2026_05_12",
        "NFP_2026_06_05",
        "FOMC_2026_06_17",
    ]


def test_event_blackout_fallback_respects_configured_pre_window(tmp_path) -> None:
    fallback_path = tmp_path / "blackouts.json"
    fallback_path.write_text(
        """
{
  "windows": [
    {"label": "CPI_2026_05_12", "start_utc": "2026-05-12T12:00:00Z", "end_utc": "2026-05-12T13:00:00Z"}
  ]
}
""",
        encoding="utf-8",
    )

    events = build_micro_live_event_blackouts._events_from_fallback_contract(
        str(fallback_path),
        years={2026},
        pre_minutes=30,
    )

    assert events[0]["event_ts_utc"] == datetime(2026, 5, 12, 12, 30, tzinfo=UTC)


def test_binance_rule_drift_snapshot_detects_field_changes() -> None:
    previous = {
        "rules": [
            {
                "symbol": "BTCUSDC",
                "quantity_step": 0.001,
                "min_quantity": 0.001,
                "tick_size": 0.1,
                "price_precision": 1,
                "quantity_precision": 3,
                "status": "TRADING",
                "contract_type": "PERPETUAL",
            }
        ]
    }
    current = {
        "rules": [
            {
                "symbol": "BTCUSDC",
                "quantity_step": 0.001,
                "min_quantity": 0.002,
                "tick_size": 0.1,
                "price_precision": 1,
                "quantity_precision": 3,
                "status": "TRADING",
                "contract_type": "PERPETUAL",
            }
        ]
    }

    changes = run_binance_rule_drift_snapshot.compare_rule_snapshots(previous=previous, current=current)

    assert changes == [
        {
            "symbol": "BTCUSDC",
            "change_type": "rule_changed",
            "fields": {"min_quantity": {"old": 0.001, "new": 0.002}},
        }
    ]


def test_binance_rule_drift_snapshot_main_writes_latest_json_atomically(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(
        run_binance_rule_drift_snapshot,
        "build_snapshot",
        lambda **_kwargs: {
            "generated_at": "2026-05-10T00:00:00Z",
            "source": "test",
            "symbols": ["BTCUSDC"],
            "rules": [],
        },
    )
    settings = get_settings()
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_symbols", "BTCUSDC")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_binance_rule_drift_snapshot.py",
            "--snapshot-dir",
            str(tmp_path),
        ],
    )

    assert run_binance_rule_drift_snapshot.main() == 0
    output = json.loads(capsys.readouterr().out)

    assert (tmp_path / "binance_rules_20260510T000000Z.json").exists()
    assert (tmp_path / "latest.json").exists()
    assert output["latest_path"].endswith("latest.json")
    latest_payload = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest_payload["overall_status"] == "PASS"
    assert latest_payload["latest_path"].endswith("latest.json")


def test_live_replay_parity_flags_flow_below_replay_baseline() -> None:
    dashboard = {
        "active_contract": {
            "flow_cadence": {"current_window_active_contract_intents_per_week": 1.0},
            "replay_flow_baseline": {
                "expected_active_contract_candidates_per_week_from_replay": 10.0,
                "observed_current_window_active_contract_intents_per_week_live": 1.0,
            },
        }
    }
    lifecycle = {
        "summary": {
            "submission_count": 0,
            "live_intents": {"total": 3, "top_block_reasons": {"validation_do_not_deploy": 3}},
        }
    }

    result = run_live_replay_parity_audit.evaluate_parity(
        dashboard=dashboard,
        lifecycle=lifecycle,
        min_flow_ratio=0.25,
    )

    assert result["status"] == "ALERT"
    assert result["live_vs_replay_flow_ratio"] == 0.1


def test_live_replay_parity_uses_local_db_dashboard_before_api(monkeypatch) -> None:
    dashboard = {
        "active_contract": {
            "replay_flow_baseline": {
                "expected_active_contract_candidates_per_week_from_replay": 1.0,
                "observed_current_window_active_contract_intents_per_week_live": 1.0,
            }
        }
    }

    monkeypatch.setattr(run_live_replay_parity_audit, "_build_dashboard_from_db", lambda **_kwargs: dashboard)
    monkeypatch.setattr(
        run_live_replay_parity_audit,
        "_request_dashboard",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("api should not be called")),
    )

    payload = run_live_replay_parity_audit.build_payload(
        base_url="http://127.0.0.1:9",
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        days=1,
        dashboard_json="",
        min_flow_ratio=0.25,
    )

    assert payload["dashboard_source"] == "local_db_replay_baseline"
    assert payload["overall_status"] == "PASS"


def test_live_replay_parity_classifies_approval_gate_blocked_flow() -> None:
    dashboard = {
        "active_contract": {
            "replay_flow_baseline": {
                "expected_active_contract_candidates_per_week_from_replay": 10.0,
                "observed_current_window_active_contract_intents_per_week_live": 0.0,
            }
        }
    }
    lifecycle = {
        "summary": {
            "submission_count": 0,
            "requested_live_count": 0,
            "rejected_or_error_count": 0,
            "entry_fill_count": 0,
            "live_intents": {
                "total": 3,
                "submit_ready": 0,
                "blocked": 3,
                "top_block_reasons": {"validation_do_not_deploy": 3},
            },
        }
    }

    result = run_live_replay_parity_audit.evaluate_parity(
        dashboard=dashboard,
        lifecycle=lifecycle,
        min_flow_ratio=0.25,
    )

    assert result["status"] == "ALERT"
    assert result["flow_diagnosis"]["stage"] == "approval_gate_blocked"
    assert result["flow_diagnosis"]["primary_reason"] == "validation_do_not_deploy"


def test_live_replay_parity_marks_sufficient_intent_flow_but_blocked_orders_as_watch() -> None:
    dashboard = {
        "active_contract": {
            "replay_flow_baseline": {
                "expected_active_contract_candidates_per_week_from_replay": 1.0,
                "observed_current_window_active_contract_intents_per_week_live": 5.0,
            }
        }
    }
    lifecycle = {
        "summary": {
            "submission_count": 0,
            "requested_live_count": 0,
            "rejected_or_error_count": 0,
            "entry_fill_count": 0,
            "live_intents": {
                "total": 2,
                "submit_ready": 0,
                "blocked": 2,
                "top_block_reasons": {"validation_do_not_deploy": 2},
            },
        }
    }

    result = run_live_replay_parity_audit.evaluate_parity(
        dashboard=dashboard,
        lifecycle=lifecycle,
        min_flow_ratio=0.25,
    )

    assert result["status"] == "WATCH"
    assert result["reason"] == "validation_do_not_deploy"
    assert result["order_flow_status"] == "WATCH"


def test_replay_validation_bridge_marks_strong_replay_evidence_as_manual_review_only() -> None:
    rows = [
        {"final_exit_realized_r": 1.5, "final_exit_reason": "target_tp2"},
        {"final_exit_realized_r": -0.5, "final_exit_reason": "session_end_flatten"},
        {"final_exit_realized_r": 1.0, "final_exit_reason": "target_tp1"},
        {"final_exit_realized_r": 0.2, "final_exit_reason": "session_end_flatten"},
    ]
    metrics = run_replay_validation_bridge._evidence_metrics(rows)
    decision = run_replay_validation_bridge._bridge_decision(
        metrics,
        {
            "min_sample": 4,
            "min_ev_r": 0.10,
            "min_ev_lower_r": -1.0,
            "min_win_rate": 0.40,
            "min_p1r": 0.30,
            "max_stop_loss_share": 0.60,
            "max_drawdown_r": 25.0,
        },
    )

    assert metrics["sample_size"] == 4
    assert metrics["ev_r"] == 0.55
    assert decision["status"] == "ELIGIBLE_FOR_MANUAL_BRIDGE_REVIEW"
    assert decision["operator_action"] == "manual_review_before_enabling_any_replay_backed_micro_live_sampling"


def test_replay_validation_bridge_blocks_weak_replay_evidence() -> None:
    metrics = run_replay_validation_bridge._evidence_metrics(
        [
            {"final_exit_realized_r": -1.0, "final_exit_reason": "stop_loss"},
            {"final_exit_realized_r": -0.2, "final_exit_reason": "session_end_flatten"},
        ]
    )
    decision = run_replay_validation_bridge._bridge_decision(
        metrics,
        {
            "min_sample": 4,
            "min_ev_r": 0.10,
            "min_ev_lower_r": 0.0,
            "min_win_rate": 0.40,
            "min_p1r": 0.30,
            "max_stop_loss_share": 0.60,
            "max_drawdown_r": 25.0,
        },
    )

    assert decision["status"] == "NOT_ELIGIBLE"
    assert "sample_below_bridge_floor" in decision["blockers"]
    assert "ev_below_bridge_floor" in decision["blockers"]


def test_replay_validation_bridge_main_writes_latest_aliases(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(
        run_replay_validation_bridge,
        "build_payload",
        lambda **_kwargs: {
            "generated_at": "2026-05-10T00:00:00Z",
            "mode": "audit_only",
            "live_approval_changed": False,
            "overall_status": "PASS",
            "reason": "all_symbols_clear_replay_validation_bridge_floor",
            "thresholds": {},
            "decision_counts": {},
            "top_blockers": {},
            "rows": [],
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_replay_validation_bridge.py",
            "--all-live-symbols",
            "--report-dir",
            str(tmp_path),
            "--no-fail-exit",
        ],
    )

    assert run_replay_validation_bridge.main() == 0
    output = json.loads(capsys.readouterr().out)

    assert (tmp_path / "replay_validation_bridge_20260510T000000Z.md").exists()
    assert (tmp_path / "latest.md").exists()
    assert (tmp_path / "latest.json").exists()
    assert output["latest_report_path"].endswith("latest.md")
    latest_payload = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest_payload["overall_status"] == "PASS"


def test_replay_validation_bridge_warns_when_material_slice_is_weak() -> None:
    payload = {
        "trade_rows": [
            {
                "symbol": "BTCUSDC",
                "direction": "long",
                "strategy_family": "session_impulse_retest",
                "entry_model": "LIMIT",
                "final_exit_realized_r": 1.0,
            },
            {
                "symbol": "BTCUSDC",
                "direction": "long",
                "strategy_family": "session_impulse_retest",
                "entry_model": "LIMIT",
                "final_exit_realized_r": 1.0,
            },
            {
                "symbol": "BTCUSDC",
                "direction": "short",
                "strategy_family": "session_impulse_retest",
                "entry_model": "LIMIT",
                "final_exit_realized_r": -1.0,
                "final_exit_reason": "stop_loss",
            },
            {
                "symbol": "BTCUSDC",
                "direction": "short",
                "strategy_family": "session_impulse_retest",
                "entry_model": "LIMIT",
                "final_exit_realized_r": 1.0,
            },
        ]
    }

    row = run_replay_validation_bridge._row_payload(
        payload=payload,
        symbol="BTCUSDC",
        thresholds={
            "min_sample": 4,
            "min_ev_r": 0.10,
            "min_ev_lower_r": -1.0,
            "min_win_rate": 0.40,
            "min_p1r": 0.30,
            "min_slice_sample": 2,
            "max_stop_loss_share": 0.60,
            "max_drawdown_r": 25.0,
        },
    )

    assert row["bridge_decision"]["status"] == "ELIGIBLE_FOR_MANUAL_BRIDGE_REVIEW_WITH_SLICE_WARNINGS"
    assert row["bridge_decision"]["warnings"][0]["slice_type"] == "direction"


def test_live_replay_parity_portfolio_aggregates_live_symbols(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "auto_trading_micro_live_allowed_symbols", "BTCUSDC,ETHUSDC")

    def fake_payload(**kwargs):
        symbol = kwargs["symbol"]
        observed = 1.0 if symbol == "BTCUSDC" else 0.0
        return {
            "symbol": symbol,
            "overall_status": "ALERT",
            "evaluation": {
                "status": "ALERT",
                "expected_per_week": 10.0,
                "observed_per_week": observed,
                "top_block_reasons": {"validation_do_not_deploy": 1},
                "flow_diagnosis": {
                    "stage": "approval_gate_blocked",
                    "primary_reason": "validation_do_not_deploy",
                },
            },
        }

    monkeypatch.setattr(run_live_replay_parity_audit, "build_payload", fake_payload)

    payload = run_live_replay_parity_audit.build_portfolio_payload(
        base_url="http://127.0.0.1:9",
        universe="usdc_perp_top30",
        days=3,
        min_flow_ratio=0.25,
    )

    assert payload["overall_status"] == "ALERT"
    assert payload["evaluation"]["expected_per_week"] == 20.0
    assert payload["evaluation"]["observed_per_week"] == 1.0
    assert payload["evaluation"]["top_block_reasons"] == {"validation_do_not_deploy": 2}
    assert payload["evaluation"]["flow_stage_counts"] == {"approval_gate_blocked": 2}


def test_reconciliation_watchdog_flags_stale_live_submission_without_ledger() -> None:
    now = datetime(2026, 5, 10, 12, tzinfo=UTC)

    result = run_live_reconciliation_watchdog.evaluate_reconciliation_watchdog(
        submissions=[
            {
                "submission_id": "sub_1",
                "symbol": "BTCUSDC",
                "client_order_id": "cid_1",
                "state": "SUBMITTED",
                "submit_status": "SUBMITTED",
                "requested_live": True,
                "submitted_at": datetime(2026, 5, 10, 11, 50, tzinfo=UTC),
                "updated_at": datetime(2026, 5, 10, 11, 50, tzinfo=UTC),
            }
        ],
        ledgers=[],
        positions=[],
        events=[],
        now=now,
        stale_minutes=3,
        event_lookback_minutes=60,
    )

    assert result["status"] == "ALERT"
    assert result["severity"] == "FAIL"
    assert result["issues"][0]["type"] == "missing_live_ledger_for_open_submission"


def test_reconciliation_watchdog_main_writes_latest_aliases(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(
        run_live_reconciliation_watchdog,
        "build_payload",
        lambda **_kwargs: {
            "generated_at": "2026-05-10T00:00:00Z",
            "window_days": 3,
            "symbols": [],
            "overall_status": "OK",
            "evaluation": {
                "status": "OK",
                "severity": "INFO",
                "alert": False,
                "reason": "no_reconciliation_gap_detected",
                "message": "reconciliation issues=0 fail=0 warn=0",
                "issues": [],
            },
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_live_reconciliation_watchdog.py",
            "--report-dir",
            str(tmp_path),
            "--no-fail-exit",
        ],
    )

    assert run_live_reconciliation_watchdog.main() == 0
    output = json.loads(capsys.readouterr().out)

    assert (tmp_path / "live_reconciliation_watchdog_20260510T000000Z.md").exists()
    assert (tmp_path / "latest.md").exists()
    assert (tmp_path / "latest.json").exists()
    assert output["latest_report_path"].endswith("latest.md")
    latest_payload = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest_payload["overall_status"] == "OK"


def test_reconciliation_watchdog_main_does_not_record_cooldown_when_delivery_fails(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    state_file = tmp_path / "state.json"

    class FakeDispatcher:
        def __init__(self, _settings) -> None:
            pass

        def dispatch(self, **_kwargs):
            return {"delivered": False, "skipped": True, "reason": "discord_not_configured"}

    monkeypatch.setattr(
        run_live_reconciliation_watchdog,
        "build_payload",
        lambda **_kwargs: {
            "generated_at": "2026-05-10T00:00:00Z",
            "window_days": 3,
            "symbols": [],
            "overall_status": "ALERT",
            "evaluation": {
                "status": "ALERT",
                "severity": "FAIL",
                "alert": True,
                "reason": "missing_live_ledger_for_open_submission",
                "message": "reconciliation issues=1 fail=1 warn=0",
                "issues": [
                    {
                        "type": "missing_live_ledger_for_open_submission",
                        "severity": "FAIL",
                        "symbol": "BTCUSDC",
                        "client_order_id": "cid_1",
                    }
                ],
            },
        },
    )
    monkeypatch.setattr(run_live_reconciliation_watchdog, "NotificationDispatcher", FakeDispatcher)
    monkeypatch.setattr(run_live_reconciliation_watchdog, "get_settings", lambda: object())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_live_reconciliation_watchdog.py",
            "--notify",
            "--state-file",
            str(state_file),
            "--no-write-report",
            "--no-fail-exit",
        ],
    )

    assert run_live_reconciliation_watchdog.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["notification"]["reason"] == "discord_not_configured"
    assert output["notification_state"]["reason"] == "delivery_not_confirmed"
    assert not state_file.exists()


def test_launchd_generator_includes_remaining_operational_guards(tmp_path) -> None:
    jobs = install_micro_live_ops_launchd.build_jobs(label_prefix="com.test.micro", python_bin="/usr/bin/python3")
    rows = install_micro_live_ops_launchd.write_plists(
        output_dir=tmp_path,
        jobs=jobs,
        working_dir=tmp_path,
        env_file="",
    )
    labels = {row["label"] for row in rows}

    assert "com.test.micro.reconciliation-watchdog" in labels
    assert "com.test.micro.boot-check" in labels
    assert "com.test.micro.ops-heartbeat" in labels
    assert "com.test.micro.replay-validation-bridge" in labels
    assert "com.test.micro.session-impulse-retest-runtime-audit" in labels
    assert any((tmp_path / f"{label}.plist").exists() for label in labels)


def test_boot_check_fails_when_reconciliation_watchdog_alerts(monkeypatch) -> None:
    monkeypatch.setattr(
        run_micro_live_boot_check.run_micro_live_runtime_guard,
        "build_payload",
        lambda **_kwargs: {"overall_status": "PASS", "blocking_failures": []},
    )
    monkeypatch.setattr(
        run_micro_live_boot_check.run_live_reconciliation_watchdog,
        "build_payload",
        lambda **_kwargs: {"overall_status": "ALERT", "evaluation": {"alert": True, "message": "gap"}},
    )
    monkeypatch.setattr(run_micro_live_boot_check.run_live_reconciliation_watchdog, "_default_stale_minutes", lambda _value: 3)
    monkeypatch.setattr(
        run_micro_live_boot_check.run_micro_live_synthetic_canary,
        "run_canary",
        lambda **_kwargs: {"overall_status": "PASS", "symbol": "BTCUSDC", "no_live_order_sent": True},
    )

    payload = run_micro_live_boot_check.build_payload(
        days=1,
        limit=10,
        symbol="BTCUSDC",
        check_binance_rules=False,
        canary_network=False,
    )

    assert payload["overall_status"] == "FAIL"
    assert payload["blocking_failure_count"] == 1


def test_boot_check_main_writes_latest_aliases(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(
        run_micro_live_boot_check,
        "build_payload",
        lambda **_kwargs: {
            "generated_at": "2026-05-10T00:00:00Z",
            "overall_status": "PASS",
            "blocking_failure_count": 0,
            "components": [],
            "next_actions": [],
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_micro_live_boot_check.py",
            "--report-dir",
            str(tmp_path),
            "--no-fail-exit",
        ],
    )

    assert run_micro_live_boot_check.main() == 0
    output = json.loads(capsys.readouterr().out)

    assert (tmp_path / "micro_live_boot_check_20260510T000000Z.md").exists()
    assert (tmp_path / "latest.md").exists()
    assert (tmp_path / "latest.json").exists()
    assert output["latest_report_path"].endswith("latest.md")
    latest_payload = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest_payload["overall_status"] == "PASS"


def test_ops_heartbeat_flags_missing_reports(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        run_micro_live_ops_heartbeat,
        "_DEFAULT_JOBS",
        {"runtime_guard": (str(tmp_path / "missing" / "*"), 15)},
    )

    result = run_micro_live_ops_heartbeat.evaluate_ops_heartbeat(now=datetime(2026, 5, 10, tzinfo=UTC))

    assert result["status"] == "FAIL"
    assert result["failures"][0]["reason"] == "missing_report"


def test_ops_heartbeat_message_separates_failures_and_warnings() -> None:
    message = run_micro_live_ops_heartbeat._message(
        {
            "overall_status": "FAIL",
            "evaluation": {
                "hard_failure_count": 1,
                "warning_count": 1,
                "hard_failures": [
                    {
                        "name": "boot_check",
                        "status": "FAIL",
                        "report_status": "FAIL",
                        "reason": "content_status_fail",
                        "age_minutes": 3.2,
                    }
                ],
                "warnings": [
                    {
                        "name": "macro_calendar_blackouts",
                        "status": "WATCH",
                        "report_status": "PASS",
                        "reason": "stale_report",
                        "status_detail": "macro_blackout_horizon_ok",
                        "horizon_days": 80.5,
                    }
                ],
            },
        }
    )

    assert "긴급: boot_check=FAIL/FAIL content_status_fail age=3.2" in message
    assert "주의: macro_calendar_blackouts=WATCH/PASS stale_report macro_blackout_horizon_ok horizon=80.5" in message
    assert "다음: FAIL은 즉시 조치" in message


def test_ops_heartbeat_cooldown_blocks_repeated_same_issue(tmp_path) -> None:
    payload = {
        "overall_status": "WATCH",
        "evaluation": {
            "issues": [
                {
                    "name": "no_order_watchdog",
                    "status": "WATCH",
                    "report_status": "ALERT",
                    "reason": "content_status_alert",
                    "status_detail": "",
                }
            ]
        },
    }
    state_file = tmp_path / "state.json"
    dedupe_key = run_micro_live_ops_heartbeat._issue_dedupe_key(payload)
    state_file.write_text(
        json.dumps({"dedupe_key": dedupe_key, "last_sent_at": "2026-05-10T00:00:00Z"}),
        encoding="utf-8",
    )

    assert (
        run_micro_live_ops_heartbeat._cooldown_allows(
            state_file=state_file,
            dedupe_key=dedupe_key,
            cooldown_minutes=360,
            now=datetime(2026, 5, 10, 1, tzinfo=UTC),
            force=False,
        )
        is False
    )
    assert run_micro_live_ops_heartbeat._cooldown_allows(
        state_file=state_file,
        dedupe_key=dedupe_key,
        cooldown_minutes=360,
        now=datetime(2026, 5, 10, 7, tzinfo=UTC),
        force=False,
    )


def test_ops_heartbeat_cooldown_allows_changed_issue(tmp_path) -> None:
    state_file = tmp_path / "state.json"
    state_file.write_text(
        json.dumps({"dedupe_key": "old", "last_sent_at": "2026-05-10T00:00:00Z"}),
        encoding="utf-8",
    )

    assert run_micro_live_ops_heartbeat._cooldown_allows(
        state_file=state_file,
        dedupe_key="new",
        cooldown_minutes=360,
        now=datetime(2026, 5, 10, 1, tzinfo=UTC),
        force=False,
    )


def test_ops_heartbeat_notification_state_requires_confirmed_delivery() -> None:
    assert run_micro_live_ops_heartbeat._notification_delivered({"delivered": True})
    assert not run_micro_live_ops_heartbeat._notification_delivered({"delivered": False, "skipped": True})
    assert not run_micro_live_ops_heartbeat._notification_delivered({})


def test_ops_heartbeat_main_does_not_record_cooldown_when_delivery_fails(monkeypatch, tmp_path, capsys) -> None:
    state_file = tmp_path / "heartbeat_state.json"

    class FakeDispatcher:
        def __init__(self, _settings) -> None:
            pass

        def dispatch(self, **_kwargs):
            return {"delivered": False, "skipped": True, "reason": "system_no_routes_configured"}

    monkeypatch.setattr(
        run_micro_live_ops_heartbeat,
        "build_payload",
        lambda: {
            "generated_at": "2026-05-10T00:00:00Z",
            "overall_status": "WATCH",
            "evaluation": {
                "hard_failure_count": 0,
                "warning_count": 1,
                "issues": [
                    {
                        "name": "no_order_watchdog",
                        "status": "WATCH",
                        "report_status": "ALERT",
                        "reason": "content_status_alert",
                    }
                ],
                "hard_failures": [],
                "warnings": [
                    {
                        "name": "no_order_watchdog",
                        "status": "WATCH",
                        "report_status": "ALERT",
                        "reason": "content_status_alert",
                    }
                ],
            },
        },
    )
    monkeypatch.setattr(run_micro_live_ops_heartbeat, "NotificationDispatcher", FakeDispatcher)
    monkeypatch.setattr(run_micro_live_ops_heartbeat, "get_settings", lambda: object())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_micro_live_ops_heartbeat.py",
            "--notify",
            "--channel",
            "system",
            "--state-file",
            str(state_file),
            "--no-write-report",
            "--no-fail-exit",
        ],
    )

    assert run_micro_live_ops_heartbeat.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["notification"]["reason"] == "system_no_routes_configured"
    assert output["notification_state"]["reason"] == "delivery_not_confirmed"
    assert not state_file.exists()


def test_ops_heartbeat_main_writes_latest_aliases(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(
        run_micro_live_ops_heartbeat,
        "build_payload",
        lambda: {
            "generated_at": "2026-05-10T00:00:00Z",
            "overall_status": "PASS",
            "evaluation": {
                "issue_count": 0,
                "failure_count": 0,
                "hard_failure_count": 0,
                "warning_count": 0,
                "jobs": [],
            },
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_micro_live_ops_heartbeat.py",
            "--report-dir",
            str(tmp_path),
            "--no-fail-exit",
        ],
    )

    assert run_micro_live_ops_heartbeat.main() == 0
    output = json.loads(capsys.readouterr().out)

    assert (tmp_path / "micro_live_ops_heartbeat_20260510T000000Z.md").exists()
    assert (tmp_path / "latest.md").exists()
    assert (tmp_path / "latest.json").exists()
    assert output["latest_report_path"].endswith("latest.md")
    latest_payload = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest_payload["overall_status"] == "PASS"
    assert latest_payload["latest_json_path"].endswith("latest.json")


def test_ops_heartbeat_atomic_write_replaces_existing_file(tmp_path) -> None:
    target = tmp_path / "latest.json"
    target.write_text("old", encoding="utf-8")

    run_micro_live_ops_heartbeat._atomic_write_text(target, '{"ok":true}')

    assert target.read_text(encoding="utf-8") == '{"ok":true}'
    assert not list(tmp_path.glob("*.tmp"))


def test_ops_heartbeat_warns_on_fresh_report_warning_status(monkeypatch, tmp_path) -> None:
    report = tmp_path / "no_order.md"
    report.write_text(
        '\n'.join(
            [
                "# report",
                "",
                "```json",
                '{"evaluation":{"status":"ALERT"}}',
                "```",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        run_micro_live_ops_heartbeat,
        "_DEFAULT_JOBS",
        {
            "no_order_watchdog": {
                "pattern": str(tmp_path / "*.md"),
                "max_age_minutes": 15,
                "pass_statuses": {"OK"},
                "watch_statuses": {"ALERT"},
            }
        },
    )

    now = datetime.fromtimestamp(report.stat().st_mtime, tz=UTC)
    result = run_micro_live_ops_heartbeat.evaluate_ops_heartbeat(now=now)

    assert result["status"] == "WATCH"
    assert result["warning_count"] == 1
    assert result["warnings"][0]["reason"] == "content_status_alert"


def test_ops_heartbeat_fails_on_fresh_report_unaccepted_status(monkeypatch, tmp_path) -> None:
    report = tmp_path / "boot_check.md"
    report.write_text("- overall_status: FAIL\n", encoding="utf-8")
    monkeypatch.setattr(
        run_micro_live_ops_heartbeat,
        "_DEFAULT_JOBS",
        {
            "boot_check": {
                "pattern": str(tmp_path / "*.md"),
                "max_age_minutes": 15,
                "pass_statuses": {"PASS"},
            }
        },
    )

    now = datetime.fromtimestamp(report.stat().st_mtime, tz=UTC)
    result = run_micro_live_ops_heartbeat.evaluate_ops_heartbeat(now=now)

    assert result["status"] == "FAIL"
    assert result["hard_failure_count"] == 1
    assert result["hard_failures"][0]["reason"] == "content_status_fail"


def test_ops_heartbeat_fails_when_checked_report_has_no_status(monkeypatch, tmp_path) -> None:
    report = tmp_path / "runtime_guard.md"
    report.write_text("# malformed report\n", encoding="utf-8")
    monkeypatch.setattr(
        run_micro_live_ops_heartbeat,
        "_DEFAULT_JOBS",
        {
            "runtime_guard": {
                "pattern": str(tmp_path / "*.md"),
                "max_age_minutes": 15,
                "pass_statuses": {"PASS"},
            }
        },
    )

    now = datetime.fromtimestamp(report.stat().st_mtime, tz=UTC)
    result = run_micro_live_ops_heartbeat.evaluate_ops_heartbeat(now=now)

    assert result["status"] == "FAIL"
    assert result["hard_failures"][0]["reason"] == "content_status_missing"


def test_ops_heartbeat_checks_macro_blackout_horizon(monkeypatch, tmp_path) -> None:
    now = datetime(2026, 5, 10, tzinfo=UTC)
    contract = tmp_path / "micro_live_event_blackouts_test.json"
    contract.write_text(
        json.dumps(
            {
                "windows": [
                    {
                        "label": "CPI_2026_06_10",
                        "start_utc": (now + timedelta(days=31)).isoformat().replace("+00:00", "Z"),
                        "end_utc": (now + timedelta(days=31, minutes=45)).isoformat().replace("+00:00", "Z"),
                    },
                    {
                        "label": "FOMC_2026_07_29",
                        "start_utc": (now + timedelta(days=80)).isoformat().replace("+00:00", "Z"),
                        "end_utc": (now + timedelta(days=80, minutes=45)).isoformat().replace("+00:00", "Z"),
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        run_micro_live_ops_heartbeat,
        "_DEFAULT_JOBS",
        {
            "macro_calendar_blackouts": {
                "pattern": str(tmp_path / "micro_live_event_blackouts_*.json"),
                "max_age_minutes": 15,
                "content_type": "macro_blackout_contract",
                "pass_statuses": {"PASS"},
                "min_horizon_days": 45,
            }
        },
    )

    result = run_micro_live_ops_heartbeat.evaluate_ops_heartbeat(now=now)

    assert result["status"] == "PASS"
    assert result["jobs"][0]["report_status"] == "PASS"
    assert result["jobs"][0]["horizon_days"] >= 80
    assert result["jobs"][0]["status_detail"] == "macro_blackout_horizon_ok"


def test_ops_heartbeat_fails_when_macro_blackout_horizon_is_short(monkeypatch, tmp_path) -> None:
    now = datetime(2026, 5, 10, tzinfo=UTC)
    contract = tmp_path / "micro_live_event_blackouts_short.json"
    contract.write_text(
        json.dumps(
            {
                "windows": [
                    {
                        "label": "CPI_2026_05_12",
                        "start_utc": (now + timedelta(days=2)).isoformat().replace("+00:00", "Z"),
                        "end_utc": (now + timedelta(days=2, minutes=45)).isoformat().replace("+00:00", "Z"),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        run_micro_live_ops_heartbeat,
        "_DEFAULT_JOBS",
        {
            "macro_calendar_blackouts": {
                "pattern": str(tmp_path / "micro_live_event_blackouts_*.json"),
                "max_age_minutes": 15,
                "content_type": "macro_blackout_contract",
                "pass_statuses": {"PASS"},
                "min_horizon_days": 45,
            }
        },
    )

    result = run_micro_live_ops_heartbeat.evaluate_ops_heartbeat(now=now)

    assert result["status"] == "FAIL"
    assert result["hard_failures"][0]["reason"] == "content_status_fail"
    assert result["hard_failures"][0]["status_detail"] == "macro_blackout_horizon_below_minimum"


def test_ops_heartbeat_warns_not_fails_when_macro_blackout_file_is_stale_but_horizon_ok(monkeypatch, tmp_path) -> None:
    contract = tmp_path / "micro_live_event_blackouts_old.json"
    contract.write_text("{}", encoding="utf-8")
    mtime = datetime.fromtimestamp(contract.stat().st_mtime, tz=UTC)
    now = mtime + timedelta(minutes=60)
    contract.write_text(
        json.dumps(
            {
                "windows": [
                    {
                        "label": "FOMC_future",
                        "start_utc": (now + timedelta(days=80)).isoformat().replace("+00:00", "Z"),
                        "end_utc": (now + timedelta(days=80, minutes=45)).isoformat().replace("+00:00", "Z"),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        run_micro_live_ops_heartbeat,
        "_DEFAULT_JOBS",
        {
            "macro_calendar_blackouts": {
                "pattern": str(tmp_path / "micro_live_event_blackouts_*.json"),
                "max_age_minutes": 15,
                "content_type": "macro_blackout_contract",
                "pass_statuses": {"PASS"},
                "min_horizon_days": 45,
                "stale_status": "WATCH",
            }
        },
    )

    result = run_micro_live_ops_heartbeat.evaluate_ops_heartbeat(now=now)

    assert result["status"] == "WATCH"
    assert result["hard_failure_count"] == 0
    assert result["warning_count"] == 1
    assert result["warnings"][0]["reason"] == "stale_report"
    assert result["warnings"][0]["report_status"] == "PASS"


def test_ops_heartbeat_uses_configured_macro_blackout_path_over_newer_glob_match(monkeypatch, tmp_path) -> None:
    now = datetime(2026, 5, 10, tzinfo=UTC)
    configured = tmp_path / "micro_live_event_blackouts_configured.json"
    configured.write_text(
        json.dumps(
            {
                "windows": [
                    {
                        "label": "CPI_short",
                        "start_utc": (now + timedelta(days=2)).isoformat().replace("+00:00", "Z"),
                        "end_utc": (now + timedelta(days=2, minutes=45)).isoformat().replace("+00:00", "Z"),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    newer_unconfigured = tmp_path / "micro_live_event_blackouts_newer.json"
    newer_unconfigured.write_text(
        json.dumps(
            {
                "windows": [
                    {
                        "label": "FOMC_long",
                        "start_utc": (now + timedelta(days=90)).isoformat().replace("+00:00", "Z"),
                        "end_utc": (now + timedelta(days=90, minutes=45)).isoformat().replace("+00:00", "Z"),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    settings = type(
        "Settings",
        (),
        {
            "auto_trading_micro_live_event_blackout_path": str(configured),
            "auto_trading_micro_live_event_blackout_min_horizon_days": 45,
        },
    )()
    monkeypatch.setattr(run_micro_live_ops_heartbeat, "get_settings", lambda: settings)
    monkeypatch.setattr(
        run_micro_live_ops_heartbeat,
        "_DEFAULT_JOBS",
        {
            "macro_calendar_blackouts": {
                "pattern": str(tmp_path / "micro_live_event_blackouts_*.json"),
                "path_setting": "auto_trading_micro_live_event_blackout_path",
                "max_age_minutes": 15,
                "content_type": "macro_blackout_contract",
                "pass_statuses": {"PASS"},
                "min_horizon_days": 45,
            }
        },
    )

    result = run_micro_live_ops_heartbeat.evaluate_ops_heartbeat(now=now)

    assert result["status"] == "FAIL"
    assert result["hard_failures"][0]["latest_path"].endswith("micro_live_event_blackouts_configured.json")
    assert result["hard_failures"][0]["path_source"] == "configured_path"
    assert result["hard_failures"][0]["status_detail"] == "macro_blackout_horizon_below_minimum"


def test_no_order_watchdog_cooldown_allows_new_dedupe_key(tmp_path) -> None:
    state_file = tmp_path / "state.json"
    state_file.write_text(
        '{"dedupe_key":"old","last_sent_at":"2026-05-10T00:00:00Z"}',
        encoding="utf-8",
    )

    assert run_micro_live_no_order_watchdog._cooldown_allows(
        state_file=state_file,
        dedupe_key="new",
        cooldown_minutes=360,
        now=datetime(2026, 5, 10, 1, tzinfo=UTC),
        force=False,
    )
