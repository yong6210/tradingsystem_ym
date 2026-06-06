from scripts.run_market_state_rotation_v6_paper_bridge_audit import build_paper_bridge_audit_report


def test_paper_bridge_audit_blocks_when_v6_runtime_bridge_has_no_intents_or_submissions() -> None:
    report = build_paper_bridge_audit_report(
        {
            "window_start": "2026-01-01T00:00:00+00:00",
            "window_days": 30,
            "summary": {"live_intents": {"total": 0, "submit_ready": 0}},
            "rows": [],
        }
    )

    assert report["overall_status"] == "blocked_runtime_bridge_missing"
    assert "v6_order_intent_bridge_missing" in report["blockers"]
    assert "v6_order_submission_bridge_missing" in report["blockers"]
    assert "connect_market_state_rotation_v6_runtime_decisions_to_order_intent_creation_in_paper_mode" in report["next_actions"]


def test_paper_bridge_audit_detects_collecting_state_after_v6_submissions_start() -> None:
    report = build_paper_bridge_audit_report(
        {
            "summary": {"live_intents": {"total": 3, "submit_ready": 2}},
            "rows": [
                {
                    "symbol": "BTCUSDT",
                    "strategy_family": "market_state_rotation_v6",
                    "entry_fill_count": 1,
                    "submission_id": "sub_1",
                }
            ],
        },
        min_tiny_canary_fill_samples=2,
        min_full_live_fill_samples=3,
    )

    assert report["overall_status"] == "collecting_required"
    assert report["counts"]["v6_entry_fill_rows"] == 1
    assert "v6_order_intent_bridge_missing" not in report["blockers"]
    assert "tiny_canary_paper_fill_samples_missing" in report["blockers"]


def test_paper_bridge_audit_marks_tiny_canary_floor_when_20_rows_exist_but_100_do_not() -> None:
    rows = [
        {
            "symbol": "BTCUSDT",
            "strategy_family": "market_state_rotation_v6",
            "entry_fill_count": 1,
            "submission_id": f"sub_{idx}",
        }
        for idx in range(20)
    ]
    report = build_paper_bridge_audit_report(
        {"summary": {"live_intents": {"total": 20, "submit_ready": 20}}, "rows": rows},
        min_tiny_canary_fill_samples=20,
        min_full_live_fill_samples=100,
    )

    assert report["overall_status"] == "tiny_canary_sample_floor_met"
    assert "tiny_canary_paper_fill_samples_missing" not in report["blockers"]
    assert "full_live_paper_fill_samples_missing" in report["blockers"]
