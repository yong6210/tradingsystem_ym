import json

from scripts.run_market_state_rotation_v6_execution_shadow_audit import (
    REQUIRED_SAFETY_CONTROLS,
    _load_rows,
    _markdown,
    build_execution_shadow_audit_report,
)


def _stress_report(*, replay_status: str = "pass") -> dict:
    return {
        "symbol": "BTCUSDT",
        "execution_readiness_checklist": {
            "overall_status": "shadow_only",
            "items": [
                {
                    "name": "replay_stress_floor",
                    "status": replay_status,
                    "evidence": {"replay_deployment_readiness_verdict": replay_status},
                },
                {
                    "name": "proxy_replay_gap_review",
                    "status": "watch",
                    "evidence": {"status": "proxy_conservative_replay_pass"},
                },
                {
                    "name": "live_fill_slippage_calibration",
                    "status": "required",
                    "evidence": "collect shadow fills",
                },
                {
                    "name": "order_safety_controls",
                    "status": "required",
                    "evidence": "verify controls",
                },
            ],
        },
        "replay_adjusted_worst_stress_summary": {
            "deployment_readiness_verdict": replay_status,
            "scenario": "cost_x3_funding3",
        },
    }


def _fills(count: int = 5, *, slippage_bps: float = 2.0) -> list[dict]:
    rows: list[dict] = []
    for idx in range(count):
        rows.append(
            {
                "timestamp": f"2026-01-01T00:{idx:02d}:00Z",
                "symbol": "BTCUSDT",
                "strategy_family": "market_state_rotation_v6",
                "decision_id": f"msrv6-{idx}",
                "action": "add" if idx % 2 == 0 else "remove",
                "side": "long",
                "status": "filled",
                "slippage_bps": slippage_bps + idx * 0.1,
                "spread_bps": 1.2,
                "latency_ms": 250 + idx,
                "fill_ratio": 1.0,
            }
        )
    return rows


def _safety_controls() -> dict:
    return {"controls": {name: {"verified": True, "evidence": "unit_test"} for name in REQUIRED_SAFETY_CONTROLS}}


def test_shadow_audit_requires_shadow_fill_samples_before_live_gate() -> None:
    report = build_execution_shadow_audit_report(_stress_report(), min_shadow_fill_samples=3)

    assert report["overall_status"] == "shadow_data_required"
    assert report["summary"]["ready_for_paper"] is True
    assert report["summary"]["ready_for_tiny_live_canary"] is False
    assert report["summary"]["live_order_submission_allowed"] is False
    assert "min_shadow_fill_samples" in report["summary"]["failed_gates"]
    assert "collect_market_state_rotation_v6_shadow_or_paper_fills_until_min_sample_count_is_met" in report[
        "required_next_actions"
    ]


def test_shadow_audit_blocks_bad_fill_quality_even_with_enough_samples() -> None:
    report = build_execution_shadow_audit_report(
        _stress_report(),
        _fills(4, slippage_bps=30.0),
        min_shadow_fill_samples=3,
        max_p95_adverse_slippage_bps=8.0,
        max_max_adverse_slippage_bps=25.0,
    )

    assert report["overall_status"] == "not_ready"
    assert "p95_adverse_slippage_within_limit" in report["summary"]["failed_gates"]
    assert "max_adverse_slippage_within_limit" in report["summary"]["failed_gates"]
    assert "reduce_execution_aggression_or_add_submission_filters_until_slippage_spread_latency_rejects_pass" in report[
        "required_next_actions"
    ]


def test_shadow_audit_keeps_passing_shadow_metrics_at_paper_when_safety_controls_missing() -> None:
    report = build_execution_shadow_audit_report(
        _stress_report(),
        _fills(4),
        min_shadow_fill_samples=3,
    )

    assert report["overall_status"] == "paper_ready"
    assert report["shadow_fill_metrics"]["schema_issue_total"] == 0
    assert report["summary"]["ready_for_tiny_live_canary"] is False
    assert report["summary"]["live_order_submission_allowed"] is False
    assert "order_safety_controls_verified" in report["summary"]["failed_gates"]
    assert "verify_order_safety_controls_before_any_live_canary_authority" in report["required_next_actions"]


def test_shadow_audit_allows_only_tiny_live_canary_after_fill_and_safety_pass() -> None:
    report = build_execution_shadow_audit_report(
        _stress_report(),
        _fills(4),
        safety_controls=_safety_controls(),
        min_shadow_fill_samples=3,
    )

    assert report["overall_status"] == "tiny_live_canary_ready"
    assert report["summary"]["ready_for_tiny_live_canary"] is True
    assert report["summary"]["ready_for_full_live"] is False
    assert report["summary"]["live_order_submission_allowed"] is True
    assert report["summary"]["full_live_order_submission_allowed"] is False
    assert report["execution_limits"]["tiny_live_canary_size_multiplier"] == 0.10
    assert report["required_next_actions"] == [
        "run_tiny_live_canary_only_with_daily_review_and_keep_full_live_disabled"
    ]


def test_shadow_audit_blocks_source_replay_failure() -> None:
    report = build_execution_shadow_audit_report(
        _stress_report(replay_status="fail"),
        _fills(4),
        safety_controls=_safety_controls(),
        min_shadow_fill_samples=3,
    )

    assert report["overall_status"] == "not_ready"
    assert "source_replay_ready_for_shadow_collection" in report["summary"]["failed_gates"]
    assert report["summary"]["ready_for_paper"] is False


def test_shadow_audit_loads_jsonl_rows_and_markdown_surfaces_gates(tmp_path) -> None:
    path = tmp_path / "fills.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in _fills(2)), encoding="utf-8")

    rows = _load_rows(path)
    report = build_execution_shadow_audit_report(_stress_report(), rows, min_shadow_fill_samples=2)
    markdown = _markdown(report)

    assert len(rows) == 2
    assert "# Market State Rotation V6 Execution Shadow Audit" in markdown
    assert "min_shadow_fill_samples" in markdown
