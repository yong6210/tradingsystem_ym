from datetime import UTC, datetime

from scripts.run_market_state_rotation_v6_signal_drought_audit import build_signal_drought_audit


def _cycle_report(*, blockers: list[str], market_age: float = 5.0, signal_age: float = 24000.0) -> dict:
    return {
        "bridge": {
            "overall_status": "not_actionable",
            "snapshot_blockers": blockers,
            "bridge_action": "remove",
            "freshness": {
                "market_data_age_minutes": market_age,
                "signal_age_minutes": signal_age,
            },
            "runtime_load_context": {
                "days": 120,
                "load_days": 180,
                "max_cache_age_minutes": 30,
                "base_url": "https://fapi.binance.com",
            },
            "event_cadence": {
                "latest_event_ts": "2026-05-19T10:55:00+00:00",
                "latest_event_age_hours": 402.0,
                "latest_add_ts": "2026-05-19T06:35:00+00:00",
                "latest_add_age_hours": 406.0,
                "expected_days_per_add": 7.0,
                "add_wait_state": "latest_add_age_above_recent_median_gap",
            },
        },
        "collection": {
            "quote_samples": {
                "observed": 40,
                "required": 300,
                "calendar_days": 2,
                "min_calendar_days": 30,
                "distinct_hours": 5,
                "min_distinct_hours": 24,
            },
            "paper_fill": {"v6_lifecycle_rows": 0},
            "readiness": {
                "overall_status": "shadow_data_required",
                "max_authorized_stage": "paper",
                "live_order_submission_allowed": False,
                "failed_gates": ["min_shadow_fill_samples"],
                "pending_gates": ["p95_latency_within_limit"],
            },
        },
        "bottleneck_diagnosis": {
            "paper_missing_shadow_fills": 100,
        },
    }


def _entry_audit(*, eligible: int = 0, low_quality: bool = True) -> dict:
    return {
        "status": "entry_filter_sparsity_review_required",
        "diagnosis": {
            "dominant_soft_contexts_are_low_quality": low_quality,
            "eligible_probe_context_count": eligible,
            "rejected_soft_context_count": 6561,
            "mc04_soft_context_count": 2761,
            "mc04_broad_relaxation_rejected": True,
            "recommended_experiment_scope": (
                "mc12_quality_gated_micro_probe_only"
                if eligible
                else "do_not_relax_current_top_soft_contexts_without_new_evidence"
            ),
        },
    }


def test_signal_drought_audit_classifies_low_quality_abstention() -> None:
    report = build_signal_drought_audit(
        _cycle_report(blockers=["signal_stale"]),
        _entry_audit(),
        generated_at=datetime(2026, 6, 5, tzinfo=UTC),
    )

    assert report["status"] == "healthy_abstention_waiting_for_quality_signal"
    assert report["classification"]["primary_cause"] == "strategy_abstaining_from_low_quality_soft_contexts"
    assert report["classification"]["market_data_stale"] is False
    assert report["collection_state"]["quote"]["first_missing_floor"] == "quote_samples"
    assert report["entry_quality"]["eligible_probe_context_count"] == 0
    assert "do_not_relax_current_low_quality_soft_contexts" in report["next_actions"]
    assert "keep_live_disabled_until_shadow_fill_and_execution_gates_pass" in report["next_actions"]
    assert report["no_live_order_sent"] is True


def test_signal_drought_audit_prioritizes_market_data_refresh() -> None:
    report = build_signal_drought_audit(
        _cycle_report(blockers=["market_data_stale", "signal_stale"], market_age=90.0),
        _entry_audit(),
    )

    assert report["status"] == "data_refresh_required"
    assert report["classification"]["primary_cause"] == "market_data_not_fresh_enough_for_runtime_bridge"
    assert report["classification"]["market_data_stale"] is True
    assert "rerun_collection_cycle_with_runtime_fresh_cache_before_interpreting_signal_drought" in report["next_actions"]


def test_signal_drought_audit_exposes_quality_gated_probe_candidate() -> None:
    report = build_signal_drought_audit(
        _cycle_report(blockers=["signal_stale"]),
        _entry_audit(eligible=75, low_quality=False),
    )

    assert report["status"] == "quality_gated_probe_review_available"
    assert report["entry_quality"]["recommended_experiment_scope"] == "mc12_quality_gated_micro_probe_only"
    assert "test_only_quality_gated_mc12_micro_probe_in_walk_forward_or_paper" in report["next_actions"]
