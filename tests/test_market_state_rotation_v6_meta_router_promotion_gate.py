from datetime import UTC, datetime

from scripts.run_market_state_rotation_v6_meta_router_promotion_gate import (
    build_meta_router_promotion_gate,
)


def _compare(best_decision: str = "promotion_candidate_after_formal_wfo") -> dict:
    return {
        "best_candidate": {
            "recipe_id": "router_contract_observe_only_formal",
            "decision": best_decision,
            "report_path": "reports/formal.json",
            "lineage": {"guard_status": "pass", "unresolved_material_drift_count": 0},
            "candidate": {
                "fold_count": 16,
                "compounded_return_pct": 25857.0416,
                "min_return_pct": 16.5119,
                "max_drawdown_pct": 14.9814,
                "avg_cost_drag_pct": 7.5657,
                "trade_like_events": 290,
                "return_delta_vs_baseline_pct": 0.0,
                "drawdown_delta_vs_baseline_pct": 0.0,
                "cost_delta_vs_baseline_pct": 0.0,
                "router_mode_summary": {"active_modes": ["trend_reaction", "risk_off"]},
            },
        }
    }


def _readiness(*, ready_for_paper: bool = True, execution_parity_passed: bool = False) -> dict:
    blockers = [] if execution_parity_passed else ["live_or_paper_execution_parity_available"]
    return {
        "input_walk_report": "reports/formal.json",
        "stage": "paper_only" if ready_for_paper else "research_only",
        "ready_for_paper": ready_for_paper,
        "ready_for_tiny_canary": False,
        "ready_for_full_live": False,
        "blockers": blockers,
        "warnings": ["all_exact_30d_windows_positive"],
        "stage_blockers": {"paper": [], "tiny_canary": blockers, "full_live": blockers},
        "deployment_limits": {"recommended_max_size_multiplier": 0.2373},
        "execution_parity": {
            "available": execution_parity_passed,
            "passed": execution_parity_passed,
            "blockers": [] if execution_parity_passed else ["execution_parity_report_missing"],
        },
    }


def test_meta_router_promotion_gate_blocks_live_until_execution_parity() -> None:
    report = build_meta_router_promotion_gate(
        compare_report=_compare(),
        readiness_report=_readiness(),
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    assert report["no_live_order_sent"] is True
    assert report["promotion_decision"] == "paper_ready_pending_execution_parity"
    assert report["next_blocker"] == "live_or_paper_execution_parity_available"
    assert report["candidate"]["recipe_id"] == "router_contract_observe_only_formal"
    assert report["candidate"]["lineage"]["unresolved_material_drift_count"] == 0
    assert report["readiness_candidate_alignment"]["passed"] is True


def test_meta_router_promotion_gate_requires_formal_candidate() -> None:
    report = build_meta_router_promotion_gate(
        compare_report=_compare(best_decision="smoke_pass_run_formal_wfo"),
        readiness_report=_readiness(),
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    assert report["promotion_decision"] == "blocked_no_formal_wfo_promotion_candidate"
    assert report["decision_reasons"] == ["best_candidate_is_not_formal_promotion_candidate"]


def test_meta_router_promotion_gate_blocks_mismatched_readiness_report() -> None:
    readiness = _readiness()
    readiness["input_walk_report"] = "reports/older_candidate.json"

    report = build_meta_router_promotion_gate(
        compare_report=_compare(),
        readiness_report=readiness,
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    assert report["promotion_decision"] == "blocked_readiness_candidate_mismatch"
    assert report["next_blocker"] == "readiness_candidate_report_mismatch"
    assert report["readiness_candidate_alignment"]["passed"] is False


def test_meta_router_promotion_gate_distinguishes_attached_failed_parity() -> None:
    readiness = _readiness()
    readiness["execution_parity"] = {
        "available": True,
        "passed": False,
        "blockers": ["execution_journal_missing", "insufficient_execution_sample_count"],
    }

    report = build_meta_router_promotion_gate(
        compare_report=_compare(),
        readiness_report=readiness,
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    assert report["promotion_decision"] == "paper_ready_pending_execution_parity"
    assert report["decision_reasons"] == [
        "formal_wfo_passed",
        "paper_readiness_passed",
        "execution_parity_not_passed",
    ]
