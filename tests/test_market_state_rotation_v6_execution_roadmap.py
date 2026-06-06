from scripts.run_market_state_rotation_v6_execution_roadmap import build_execution_roadmap_report


def _progress_report() -> dict:
    return {
        "readiness_status": "shadow_data_required",
        "shadow_collection": {
            "required_shadow_fill_samples": 100,
            "observed_shadow_fill_samples": 0,
            "eta_days": {
                "pooled_rate": 480.0,
                "median_fold_rate": 500.0,
            },
        },
        "historical_event_rates": {
            "pooled_events_per_day": 0.2,
            "median_fold_events_per_day": 0.18,
            "p10_fold_events_per_day": 0.1,
            "p90_fold_events_per_day": 0.33,
        },
        "safety_collection": {
            "verified_count": 0,
            "required_count": 10,
            "missing_or_failed": [
                "kill_switch_verified",
                "max_daily_loss_verified",
                "leverage_cap_verified",
                "idempotent_client_order_id_verified",
            ],
            "stale_sources": [
                {
                    "name": "live_leverage_cap_sync",
                    "age_hours": 48,
                    "refresh_command": "uv run python scripts/run_live_leverage_cap_sync.py --no-fail-exit",
                }
            ],
            "manual_only_required": [
                {
                    "name": "kill_switch_verified",
                    "required_evidence": "kill switch drill",
                },
                {
                    "name": "max_daily_loss_verified",
                    "required_evidence": "daily loss drill",
                },
                {
                    "name": "idempotent_client_order_id_verified",
                    "required_evidence": "duplicate id drill",
                },
            ],
        },
    }


def test_execution_roadmap_marks_fill_only_path_impractical_and_orders_stages() -> None:
    report = build_execution_roadmap_report(
        _progress_report(),
        input_progress_report="reports/progress.json",
        max_fill_only_eta_days=90,
        tiny_canary_min_fill_samples=20,
        required_quote_samples=300,
    )

    assert report["status"] == "roadmap_ready"
    assert report["source_progress_report"] == "reports/progress.json"
    assert report["diagnosis"]["fill_only_collection_impractical"] is True
    assert report["shadow_fill_plan"]["tiny_canary_missing_fill_samples"] == 20
    assert report["shadow_fill_plan"]["tiny_canary_eta_days"]["pooled_rate"] == 100.0
    assert report["quote_shadow_contract"]["required_quote_samples"] == 300
    assert report["quote_shadow_contract"]["min_distinct_hours"] == 24
    assert report["safety_plan"]["stale_source_count"] == 1
    assert report["safety_plan"]["manual_drills"][0]["name"] == "kill_switch_verified"
    assert [stage["name"] for stage in report["stages"]] == [
        "refresh_operation_reports",
        "manual_safety_drills",
        "quote_liquidity_shadow_collection",
        "paper_fill_collection",
        "tiny_live_canary_review",
        "full_live_review",
    ]
    assert "fill_only_collection_too_slow_for_practical_iteration" in report["blockers"]
    assert "do_not_enable_full_live_from_backtest_only" in report["non_negotiables"]
    assert (
        "do_not_lower_full_live_fill_floor_below_100_without_separate_canary_live_parity_evidence"
        in report["non_negotiables"]
    )


def test_execution_roadmap_reduces_blockers_when_samples_and_safety_are_done() -> None:
    progress = _progress_report()
    progress["shadow_collection"]["observed_shadow_fill_samples"] = 20
    progress["safety_collection"]["stale_sources"] = []
    progress["safety_collection"]["manual_only_required"] = []
    progress["safety_collection"]["missing_or_failed"] = []
    progress["safety_collection"]["verified_count"] = 10

    report = build_execution_roadmap_report(progress, max_fill_only_eta_days=999)

    assert "stale_operation_reports" not in report["blockers"]
    assert "manual_safety_drills_missing" not in report["blockers"]
    assert "paper_fill_samples_missing" not in report["blockers"]
    assert report["stages"][0]["status"] == "done"
    assert report["stages"][1]["status"] == "done"
    assert report["stages"][3]["status"] == "done"


def test_execution_roadmap_sanitizes_refresh_commands_that_could_mutate_live_state() -> None:
    progress = _progress_report()
    progress["safety_collection"]["stale_sources"] = [
        {
            "name": "live_account_protection",
            "refresh_command": "uv run python scripts/run_live_account_protection_audit.py --no-fail-exit",
        },
        {
            "name": "micro_live_synthetic_canary",
            "refresh_command": "uv run python scripts/run_micro_live_synthetic_canary.py",
        },
    ]

    report = build_execution_roadmap_report(progress)
    commands = report["stages"][0]["commands"]

    assert commands[0].endswith(
        "scripts/run_live_account_protection_audit.py --no-fail-exit --no-flatten-missing-stop --no-cancel-unexpected-open-orders"
    )
    assert commands[1].endswith(
        "scripts/run_micro_live_synthetic_canary.py --symbol BTCUSDT --no-private-balance --no-fail-exit"
    )


def test_execution_roadmap_tracks_quote_shadow_audit_progress() -> None:
    quote_report = {
        "overall_status": "INCOMPLETE",
        "eligible_row_count": 2,
        "calendar_day_count": 1,
        "distinct_hour_count": 1,
        "metrics": {
            "p95_spread_bps": 0.1,
            "p95_market_slippage_bps": 0.2,
            "p95_latency_ms": 50.0,
        },
        "blockers": ["quote_samples_missing", "calendar_days_missing", "distinct_hours_missing"],
    }

    report = build_execution_roadmap_report(
        _progress_report(),
        quote_shadow_report=quote_report,
        input_quote_shadow_report="reports/quote.json",
    )

    quote_contract = report["quote_shadow_contract"]
    quote_stage = [stage for stage in report["stages"] if stage["name"] == "quote_liquidity_shadow_collection"][0]

    assert quote_contract["input_quote_shadow_report"] == "reports/quote.json"
    assert quote_contract["observed_quote_samples"] == 2
    assert quote_contract["observed_calendar_days"] == 1
    assert quote_contract["observed_distinct_hours"] == 1
    assert quote_stage["status"] == "collecting"
    assert quote_stage["blockers"] == ["quote_samples_missing", "calendar_days_missing", "distinct_hours_missing"]
    assert "quote_shadow_collection_incomplete" in report["blockers"]


def test_execution_roadmap_tracks_paper_runtime_bridge_blocker() -> None:
    paper_bridge = {
        "overall_status": "blocked_runtime_bridge_missing",
        "counts": {
            "v6_intents": 0,
            "v6_submit_ready_intents": 0,
            "v6_submissions": 0,
            "v6_entry_fill_rows": 0,
        },
        "blockers": [
            "v6_order_intent_bridge_missing",
            "v6_order_submission_bridge_missing",
            "tiny_canary_paper_fill_samples_missing",
        ],
        "next_actions": ["connect_market_state_rotation_v6_runtime_decisions_to_order_intent_creation_in_paper_mode"],
    }

    report = build_execution_roadmap_report(
        _progress_report(),
        paper_bridge_report=paper_bridge,
        input_paper_bridge_report="reports/paper_bridge.json",
    )
    paper_stage = [stage for stage in report["stages"] if stage["name"] == "paper_fill_collection"][0]

    assert report["input_paper_bridge_report"] == "reports/paper_bridge.json"
    assert report["paper_bridge_plan"]["audit_status"] == "blocked_runtime_bridge_missing"
    assert "paper_runtime_bridge_missing" in report["blockers"]
    assert "v6_order_intent_bridge_missing" in paper_stage["blockers"]
    assert "missing_fill_samples:20" in paper_stage["blockers"]


def test_execution_roadmap_distinguishes_implemented_bridge_waiting_for_fresh_signal() -> None:
    paper_bridge = {
        "overall_status": "blocked_runtime_bridge_missing",
        "counts": {
            "v6_intents": 0,
            "v6_submit_ready_intents": 0,
            "v6_submissions": 0,
            "v6_entry_fill_rows": 0,
        },
        "blockers": [
            "v6_order_intent_bridge_missing",
            "v6_order_submission_bridge_missing",
            "tiny_canary_paper_fill_samples_missing",
        ],
    }
    bridge_tick = {
        "overall_status": "not_actionable",
        "apply_paper": True,
        "snapshot": {
            "overall_status": "not_actionable",
            "blockers": ["signal_stale"],
            "bridge_action": "remove",
            "freshness": {"signal_age_minutes": 1000.0},
        },
    }

    report = build_execution_roadmap_report(
        _progress_report(),
        paper_bridge_report=paper_bridge,
        paper_bridge_tick_report=bridge_tick,
        input_paper_bridge_tick_report="reports/bridge_tick.json",
    )
    paper_stage = [stage for stage in report["stages"] if stage["name"] == "paper_fill_collection"][0]

    assert "paper_runtime_bridge_missing" not in report["blockers"]
    assert "paper_runtime_bridge_waiting_for_fresh_signal" in report["blockers"]
    assert "fresh_v6_signal_missing" in paper_stage["blockers"]
    assert "v6_order_intent_bridge_missing" not in paper_stage["blockers"]
    assert report["paper_bridge_plan"]["runtime_tick"]["snapshot_blockers"] == ["signal_stale"]
