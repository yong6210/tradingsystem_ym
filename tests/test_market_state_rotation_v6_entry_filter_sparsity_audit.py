from datetime import UTC, datetime

from scripts.run_market_state_rotation_v6_entry_filter_sparsity_audit import build_entry_filter_sparsity_audit


def test_entry_filter_sparsity_audit_flags_soft_confluence_dominance() -> None:
    cycle_report = {
        "bridge": {
            "event_cadence": {
                "add_event_count": 18,
                "add_events_per_day": 0.15,
                "expected_days_per_add": 6.6667,
                "latest_add_age_hours": 402.0,
                "median_add_gap_hours": 72.0,
                "latest_add_age_to_median_gap": 5.5,
                "add_wait_state": "latest_add_age_above_recent_median_gap",
            },
            "top_no_trade_reasons": [
                {"reason": "no_trade_MC12_low_confluence", "count": 100},
                {"reason": "no_trade_MC04_no_clear_first_touch", "count": 80},
                {"reason": "no_trade_MC27_time_event_chase_risk", "count": 5},
            ],
            "no_trade_hotspots": {
                "top_no_trade_contexts": {
                    "MC12_low_confluence|long|with_trend|uptrend|normal|score_0-3|edge_1-2|stack_1-2|ext_0-0.75|break_0-0.1": 60,
                    "MC04_no_clear_first_touch|short|with_trend|downtrend|hour_open|score_0-3|edge_0-1|stack_0-1|ext_1.5-2.5|break_0-0.1": 20,
                },
                "no_trade_reason_side_counts": {
                    "MC12_low_confluence|long": 60,
                    "MC04_no_clear_first_touch|short": 20,
                },
                "no_trade_reason_regime_counts": {
                    "MC12_low_confluence|uptrend": 60,
                    "MC04_no_clear_first_touch|downtrend": 20,
                },
            },
        }
    }

    report = build_entry_filter_sparsity_audit(
        cycle_report,
        input_cycle_report="reports/cycle.json",
        generated_at=datetime(2026, 6, 5, tzinfo=UTC),
    )

    assert report["status"] == "entry_filter_sparsity_review_required"
    assert report["no_live_order_sent"] is True
    assert report["cadence"]["latest_add_age_days"] == 16.75
    assert report["reason_class_counts"]["soft_candidate"] == 180
    assert report["reason_class_counts"]["hard_guard"] == 5
    assert report["diagnosis"]["primary_issue"] == "soft_confluence_filters_are_dominating_current_no_trade_distribution"
    assert report["diagnosis"]["primary_context"]["reason"] == "MC12_low_confluence"
    assert report["diagnosis"]["primary_context"]["side"] == "long"
    assert report["diagnosis"]["primary_context"]["execution_context"] == "normal"
    assert report["diagnosis"]["soft_contexts_are_mostly_normal_time"] is True
    assert report["diagnosis"]["dominant_soft_contexts_are_low_quality"] is True
    assert report["diagnosis"]["eligible_probe_context_count"] == 0
    assert report["diagnosis"]["rejected_soft_context_count"] == 80
    assert report["diagnosis"]["mc04_broad_relaxation_rejected"] is True
    assert (
        report["diagnosis"]["recommended_experiment_scope"]
        == "do_not_relax_current_top_soft_contexts_without_new_evidence"
    )
    assert report["no_trade_hotspots"]["context_class_counts"]["soft_candidate"] == 80
    assert report["no_trade_hotspots"]["reason_side_counts"]["MC12_low_confluence|long"] == 60
    assert (
        report["no_trade_hotspots"]["context_class_counts"]["probe_quality_reject_low_quality_soft_context"]
        == 80
    )
    assert report["experiment_backlog"][0]["name"] == "quality_gated_mc12_near_miss_micro_probe"
    assert report["experiment_backlog"][1]["name"] == "mc04_first_touch_observation_only"
    assert "do_not_relax_hard_guards_directly" in report["non_negotiables"]


def test_entry_filter_sparsity_audit_keeps_hard_guard_dominance_separate() -> None:
    cycle_report = {
        "bridge": {
            "event_cadence": {
                "expected_days_per_add": 3.0,
                "latest_add_age_hours": 240.0,
                "add_wait_state": "latest_add_age_above_recent_median_gap",
            },
            "top_no_trade_reasons": [
                {"reason": "no_trade_MC27_time_event_chase_risk", "count": 100},
                {"reason": "no_trade_MC12_low_confluence", "count": 10},
            ],
        }
    }

    report = build_entry_filter_sparsity_audit(cycle_report)

    assert report["status"] == "entry_filter_waiting_long_but_hard_guards_dominate"
    assert report["diagnosis"]["primary_issue"] == "hard_or_context_guards_are_dominating_current_no_trade_distribution"


def test_entry_filter_sparsity_audit_allows_only_quality_gated_mc12_probe() -> None:
    cycle_report = {
        "bridge": {
            "event_cadence": {
                "expected_days_per_add": 4.0,
                "latest_add_age_hours": 220.0,
                "add_wait_state": "latest_add_age_above_recent_median_gap",
            },
            "top_no_trade_reasons": [
                {"reason": "no_trade_MC12_low_confluence", "count": 100},
                {"reason": "no_trade_MC27_time_event_chase_risk", "count": 5},
            ],
            "no_trade_hotspots": {
                "top_no_trade_contexts": {
                    "MC12_low_confluence|short|with_trend|downtrend|normal|score_4-5|edge_2-4|stack_2-4|ext_0.75-1.5|break_0-0.1": 75,
                    "MC12_low_confluence|long|against_trend|downtrend|normal|score_4-5|edge_2-4|stack_2-4|ext_0.75-1.5|break_0-0.1": 25,
                },
            },
        }
    }

    report = build_entry_filter_sparsity_audit(cycle_report)

    assert report["status"] == "entry_filter_sparsity_review_required"
    assert report["diagnosis"]["eligible_probe_context_count"] == 75
    assert report["diagnosis"]["rejected_soft_context_count"] == 25
    assert report["diagnosis"]["mc04_broad_relaxation_rejected"] is False
    assert report["diagnosis"]["recommended_experiment_scope"] == "mc12_quality_gated_micro_probe_only"
    assert (
        report["no_trade_hotspots"]["context_class_counts"]["probe_quality_eligible_mc12_quality_gated_micro_probe"]
        == 75
    )
    assert (
        report["no_trade_hotspots"]["top_contexts"][0]["probe_quality"]
        == "eligible_mc12_quality_gated_micro_probe"
    )
