from datetime import UTC, datetime

import scripts.run_market_state_rotation_v6_collection_cycle as cycle
from scripts.run_market_state_rotation_v6_collection_cycle import (
    BRIDGE_REPORT_NAME,
    CYCLE_REPORT_NAME,
    build_collection_cycle_summary,
    run_collection_cycle,
)


def test_collection_cycle_summary_prioritizes_fresh_signal_wait_and_live_lock(tmp_path) -> None:
    bridge_report = {
        "overall_status": "not_actionable",
        "apply_paper": True,
        "pre_apply_backup": None,
        "snapshot": {
            "overall_status": "not_actionable",
            "blockers": ["signal_stale"],
            "bridge_action": "remove",
            "freshness": {"signal_age_minutes": 1000.0},
            "runtime_load_context": {"load_days": 180, "max_cache_age_minutes": 30},
            "bridge_event_cadence": {
                "bridge_event_count": 3,
                "latest_event_age_hours": 240.0,
                "median_gap_hours": 24.0,
                "wait_state": "latest_signal_age_above_recent_median_gap",
                "latest_add_age_hours": 240.0,
                "expected_days_per_add": 3.0,
                "add_wait_state": "latest_add_age_above_recent_median_gap",
            },
            "top_no_trade_reasons": [
                {"reason": "no_trade_MC04_no_clear_first_touch", "count": 30},
            ],
        },
    }
    collection_report = {
        "overall_status": "collecting",
        "quote_shadow": {
            "overall_status": "INCOMPLETE",
            "eligible_row_count": 16,
            "required_quote_samples": 300,
            "calendar_day_count": 2,
            "min_calendar_days": 30,
            "calendar_days": ["2026-01-01", "2026-01-02"],
            "distinct_hour_count": 2,
            "min_distinct_hours": 24,
            "distinct_hours": ["2026-01-01T00:00Z", "2026-01-02T05:00Z"],
            "coverage": {
                "utc_hour_of_day_covered_count": 2,
                "utc_hour_of_day_covered": ["00", "05"],
                "utc_hour_of_day_missing": ["01", "02", "03", "04"],
            },
            "blockers": ["quote_samples_missing", "calendar_days_missing", "distinct_hours_missing"],
        },
        "paper_fill": {
            "status": "collecting_required",
            "bridge_status": "runtime_bridge_waiting_for_fresh_signal",
            "v6_lifecycle_rows": 0,
            "reason": "runtime_bridge_implemented_waiting_for_fresh_v6_signal",
            "next_action": "run_apply_paper_bridge_tick_when_fresh_v6_signal_appears",
        },
        "readiness": {
            "overall_status": "shadow_data_required",
            "max_authorized_stage": "paper",
            "live_order_submission_allowed": False,
            "failed_gates": ["min_shadow_fill_samples"],
            "pending_gates": ["p95_latency_within_limit"],
        },
        "roadmap": {
            "blockers": [
                "quote_shadow_collection_incomplete",
                "paper_runtime_bridge_waiting_for_fresh_signal",
                "paper_fill_samples_missing",
            ]
        },
        "captured_quote_rows": 2,
    }

    report = build_collection_cycle_summary(
        bridge_report=bridge_report,
        collection_report=collection_report,
        bridge_report_dir=tmp_path / "bridge",
        collection_report_dir=tmp_path / "collection",
        generated_at=datetime(2026, 6, 5, tzinfo=UTC),
    )

    assert report["no_live_order_sent"] is True
    assert report["bottleneck_diagnosis"]["primary_bottleneck"] == "fresh_v6_signal_missing_for_paper_fill_collection"
    assert report["bottleneck_diagnosis"]["waiting_for_fresh_signal"] is True
    assert report["bottleneck_diagnosis"]["collectable_without_fresh_signal"] == ["quote_shadow_samples"]
    assert "fresh_market_state_rotation_v6_add_or_remove_signal" in report["bottleneck_diagnosis"]["blocked_until"]
    assert report["bridge"]["snapshot_blockers"] == ["signal_stale"]
    assert report["bridge"]["freshness"]["signal_age_minutes"] == 1000.0
    assert report["bridge"]["runtime_load_context"]["load_days"] == 180
    assert report["bridge"]["event_cadence"]["wait_state"] == "latest_signal_age_above_recent_median_gap"
    assert report["bridge"]["top_no_trade_reasons"][0]["reason"] == "no_trade_MC04_no_clear_first_touch"
    assert report["collection"]["quote_samples"]["distinct_hours"] == 2
    assert report["collection"]["captured_quote_rows"] == 2
    assert report["collection"]["quote_samples"]["calendar_day_values"] == ["2026-01-01", "2026-01-02"]
    assert report["collection"]["quote_samples"]["coverage"]["utc_hour_of_day_covered"] == ["00", "05"]
    assert report["collection"]["paper_fill"]["bridge_status"] == "runtime_bridge_waiting_for_fresh_signal"
    assert report["collection"]["readiness"]["live_order_submission_allowed"] is False
    assert "rerun_cycle_until_fresh_v6_add_or_remove_signal_is_seen" in report["next_actions"]
    assert "review_v6_entry_filter_sparsity_before_waiting_for_paper_fills" in report["next_actions"]
    assert "keep_live_disabled_until_readiness_and_paper_fill_gates_pass" in report["next_actions"]


def test_run_collection_cycle_wires_bridge_report_into_collection_tick(monkeypatch, tmp_path) -> None:
    calls = {}

    def fake_bridge(**kwargs):
        calls["bridge"] = kwargs
        report_dir = kwargs["report_dir"]
        report_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "overall_status": "not_actionable",
            "apply_paper": kwargs["apply_paper"],
            "pre_apply_backup": None,
            "snapshot": {"overall_status": "not_actionable", "blockers": ["signal_stale"], "bridge_action": "remove"},
        }
        (report_dir / BRIDGE_REPORT_NAME).write_text("{}\n", encoding="utf-8")
        return payload

    def fake_collection(**kwargs):
        calls["collection"] = kwargs
        return {
            "overall_status": "collecting",
            "quote_shadow": {
                "overall_status": "INCOMPLETE",
                "eligible_row_count": 2,
                "required_quote_samples": 300,
                "calendar_day_count": 1,
                "min_calendar_days": 30,
                "distinct_hour_count": 1,
                "min_distinct_hours": 24,
                "blockers": ["quote_samples_missing", "distinct_hours_missing"],
            },
            "paper_fill": {
                "status": "collecting_required",
                "bridge_status": "runtime_bridge_waiting_for_fresh_signal",
                "v6_lifecycle_rows": 0,
                "reason": "runtime_bridge_implemented_waiting_for_fresh_v6_signal",
                "next_action": "run_apply_paper_bridge_tick_when_fresh_v6_signal_appears",
            },
            "readiness": {
                "overall_status": "shadow_data_required",
                "max_authorized_stage": "paper",
                "live_order_submission_allowed": False,
            },
            "roadmap": {"blockers": ["paper_runtime_bridge_waiting_for_fresh_signal"]},
            "bottleneck_diagnosis": {
                "primary_bottleneck": "fresh_v6_signal_missing_for_paper_fill_collection",
                "waiting_for_fresh_signal": True,
                "collectable_without_fresh_signal": ["quote_shadow_samples"],
                "blocked_until": [
                    "fresh_market_state_rotation_v6_add_or_remove_signal",
                    "min_shadow_fill_samples",
                ],
            },
        }

    monkeypatch.setattr(cycle, "run_paper_bridge_tick", fake_bridge)
    monkeypatch.setattr(cycle, "run_collection_tick", fake_collection)

    report_dir = tmp_path / "cycle"
    report = run_collection_cycle(
        source_backtest_report_path=tmp_path / "source.json",
        stress_report_path=tmp_path / "stress.json",
        walk_forward_report_path=tmp_path / "walk.json",
        manual_evidence_path=tmp_path / "manual.json",
        sample_jsonl=tmp_path / "samples.jsonl",
        report_dir=report_dir,
        apply_paper_bridge=True,
    )

    assert calls["bridge"]["report_dir"] == report_dir / "paper_bridge_tick"
    assert calls["bridge"]["apply_paper"] is True
    assert calls["bridge"]["load_days"] is None
    assert calls["collection"]["paper_bridge_tick_report_path"] == report_dir / "paper_bridge_tick" / BRIDGE_REPORT_NAME
    assert report["no_live_order_sent"] is True
    assert report["bottleneck_diagnosis"]["primary_bottleneck"] == "fresh_v6_signal_missing_for_paper_fill_collection"
    assert (report_dir / CYCLE_REPORT_NAME).exists()
