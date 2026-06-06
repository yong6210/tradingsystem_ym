from scripts.run_market_state_rotation_v6_shadow_collection_progress import (
    build_collection_progress_report,
)


def _walk_report() -> dict:
    return {
        "folds": [
            {
                "fold": 1,
                "test_start": "2026-01-01T00:00:00+00:00",
                "test_end": "2026-01-11T00:00:00+00:00",
                "test_result": {"trade_like_events": 10},
            },
            {
                "fold": 2,
                "test_start": "2026-01-11T00:00:00+00:00",
                "test_end": "2026-01-21T00:00:00+00:00",
                "test_result": {"trade_like_events": 20},
            },
        ]
    }


def _readiness_report() -> dict:
    return {
        "overall_status": "shadow_data_required",
        "summary": {
            "ready_for_tiny_live_canary": False,
            "failed_gates": ["min_shadow_fill_samples", "order_safety_controls_verified"],
        },
        "shadow_fill_export": {"row_count": 5},
        "safety_evidence_collection": {
            "overall_status": "INCOMPLETE",
            "verified_count": 1,
            "required_count": 10,
            "missing_or_failed": [
                "kill_switch_verified",
                "max_daily_loss_verified",
                "leverage_cap_verified",
                "idempotent_client_order_id_verified",
            ],
            "source_reports": {
                "live_leverage_cap_sync": {
                    "available": True,
                    "fresh": False,
                    "age_hours": 30.0,
                    "path": "reports/operations/live_leverage_cap_sync/latest.json",
                },
                "live_account_protection": {
                    "available": False,
                    "fresh": False,
                    "path": "reports/operations/live_account_protection_audit/latest.json",
                },
            },
        },
    }


def test_collection_progress_estimates_shadow_sample_eta_and_safety_work() -> None:
    report = build_collection_progress_report(
        _walk_report(),
        _readiness_report(),
        min_shadow_fill_samples=20,
    )

    shadow = report["shadow_collection"]
    safety = report["safety_collection"]
    assert report["status"] == "collection_incomplete"
    assert shadow["observed_shadow_fill_samples"] == 5
    assert shadow["missing_shadow_fill_samples"] == 15
    assert shadow["eta_days"]["pooled_rate"] == 10.0
    assert safety["stale_source_count"] == 1
    assert safety["unavailable_source_count"] == 1
    assert safety["manual_only_required_count"] == 3
    assert "shadow_fill_samples_missing" in report["blockers"]
    assert "refresh_stale_operation_reports_then_rerun_shadow_readiness_pipeline" in report["next_actions"]


def test_collection_progress_marks_ready_when_readiness_is_tiny_canary_ready() -> None:
    readiness = _readiness_report()
    readiness["overall_status"] = "tiny_live_canary_ready"
    readiness["summary"]["ready_for_tiny_live_canary"] = True
    readiness["shadow_fill_export"]["row_count"] = 20
    readiness["safety_evidence_collection"]["missing_or_failed"] = []

    report = build_collection_progress_report(
        _walk_report(),
        readiness,
        min_shadow_fill_samples=20,
    )

    assert report["status"] == "tiny_live_canary_ready"
    assert report["blockers"] == []
