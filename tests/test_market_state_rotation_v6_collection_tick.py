from datetime import UTC, datetime

from scripts.run_market_state_rotation_v6_collection_tick import (
    DEFAULT_MANUAL_EVIDENCE,
    DEFAULT_STRESS_REPORT,
    DEFAULT_WALK_FORWARD_REPORT,
    build_collection_tick_summary,
)


def test_collection_tick_summary_keeps_live_disabled_and_surfaces_remaining_collection_work() -> None:
    quote_report = {
        "overall_status": "INCOMPLETE",
        "eligible_row_count": 4,
        "required_quote_samples": 300,
        "missing_quote_samples": 296,
        "calendar_day_count": 1,
        "min_calendar_days": 30,
        "calendar_days": ["2026-01-01"],
        "distinct_hour_count": 1,
        "min_distinct_hours": 24,
        "distinct_hours": ["2026-01-01T00:00Z"],
        "coverage": {
            "utc_hour_of_day_covered_count": 1,
            "utc_hour_of_day_covered": ["00"],
            "utc_hour_of_day_missing": ["01", "02"],
        },
        "metrics": {"p95_spread_bps": 0.1, "p95_market_slippage_bps": 0.2, "p95_latency_ms": 50.0},
        "blockers": ["quote_samples_missing", "calendar_days_missing", "distinct_hours_missing"],
    }
    readiness_report = {
        "overall_status": "shadow_data_required",
        "summary": {
            "ready_for_paper": True,
            "ready_for_tiny_live_canary": False,
            "max_authorized_stage": "paper",
            "live_order_submission_allowed": False,
            "failed_gates": ["min_shadow_fill_samples"],
            "pending_gates": ["p95_latency_within_limit"],
        },
        "shadow_fill_export": {"row_count": 0, "rows": []},
    }
    progress_report = {
        "shadow_collection": {
            "observed_shadow_fill_samples": 0,
            "required_shadow_fill_samples": 100,
            "missing_shadow_fill_samples": 100,
            "eta_days": {"pooled_rate": 483.3},
        }
    }
    roadmap_report = {
        "blockers": ["quote_shadow_collection_incomplete", "paper_fill_samples_missing"],
        "stages": [
            {"order": 3, "name": "quote_liquidity_shadow_collection", "status": "collecting", "blockers": ["quote_samples_missing"]},
            {"order": 4, "name": "paper_fill_collection", "status": "blocked", "blockers": ["missing_fill_samples:20"]},
        ],
    }
    paper_bridge_report = {
        "overall_status": "blocked_runtime_bridge_missing",
        "counts": {
            "v6_intents": 0,
            "v6_submit_ready_intents": 0,
            "v6_submissions": 0,
            "v6_entry_fill_rows": 0,
        },
        "blockers": ["v6_order_intent_bridge_missing", "v6_order_submission_bridge_missing"],
    }
    paper_bridge_tick_report = {
        "overall_status": "not_actionable",
        "apply_paper": True,
        "snapshot": {
            "overall_status": "not_actionable",
            "blockers": ["signal_stale"],
            "bridge_action": "remove",
            "freshness": {"signal_age_minutes": 1000.0},
        },
    }

    report = build_collection_tick_summary(
        captured_quote_rows=2,
        quote_report=quote_report,
        readiness_report=readiness_report,
        progress_report=progress_report,
        roadmap_report=roadmap_report,
        paper_bridge_report=paper_bridge_report,
        paper_bridge_tick_report=paper_bridge_tick_report,
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert report["overall_status"] == "collecting"
    assert report["no_live_order_sent"] is True
    assert report["quote_shadow"]["eligible_row_count"] == 4
    assert report["quote_shadow"]["distinct_hour_count"] == 1
    assert report["quote_shadow"]["calendar_days"] == ["2026-01-01"]
    assert report["quote_shadow"]["coverage"]["utc_hour_of_day_missing"] == ["01", "02"]
    assert report["paper_fill"]["status"] == "collecting_required"
    assert report["paper_fill"]["bridge_status"] == "runtime_bridge_waiting_for_fresh_signal"
    assert report["paper_fill"]["v6_intents"] == 0
    assert report["paper_fill"]["bridge_blockers"] == ["fresh_v6_signal_missing"]
    assert report["paper_fill"]["reason"] == "runtime_bridge_implemented_waiting_for_fresh_v6_signal"
    assert report["paper_fill"]["runtime_bridge_tick"]["snapshot_blockers"] == ["signal_stale"]
    assert report["readiness"]["live_order_submission_allowed"] is False
    assert report["shadow_fill_progress"]["missing"] == 100
    assert report["bottleneck_diagnosis"]["primary_bottleneck"] == "fresh_v6_signal_missing_for_paper_fill_collection"
    assert report["bottleneck_diagnosis"]["waiting_for_fresh_signal"] is True
    assert report["bottleneck_diagnosis"]["collectable_without_fresh_signal"] == ["quote_shadow_samples"]
    assert report["bottleneck_diagnosis"]["quote_missing"] == {
        "samples": 296,
        "calendar_days": 29,
        "distinct_hours": 23,
    }
    assert "fresh_market_state_rotation_v6_add_or_remove_signal" in report["bottleneck_diagnosis"]["blocked_until"]
    assert report["roadmap"]["blockers"] == ["quote_shadow_collection_incomplete", "paper_fill_samples_missing"]


def test_collection_tick_defaults_track_latest_promoted_candidate_evidence() -> None:
    assert "market_state_rotation_v6_imp490_current_top_candidate_audit" in DEFAULT_WALK_FORWARD_REPORT
    assert "market_state_rotation_v6_imp491_current_system_stress_after_top_audit" in DEFAULT_STRESS_REPORT
    assert "market_state_rotation_v6_manual_safety_drills" in DEFAULT_MANUAL_EVIDENCE
