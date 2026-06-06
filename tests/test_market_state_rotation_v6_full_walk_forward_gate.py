from scripts.run_market_state_rotation_v6_full_walk_forward_gate import (
    DEFAULT_CANDIDATE_REPORT,
    build_full_walk_forward_gate_report,
)


def _report(
    *,
    compounded: float,
    drawdown: float,
    positive: int,
    events: int,
    lineage_failed: bool = False,
) -> dict:
    return {
        "folds": [{}] * 2,
        "aggregate": {
            "fold_count": 2,
            "compounded_oos_return_pct": compounded,
            "avg_oos_return_pct": compounded / 2,
            "min_oos_return_pct": min(compounded / 4, compounded / 2),
            "positive_fold_count": positive,
            "max_fold_drawdown_pct": drawdown,
            "total_trade_like_events": events,
            "avg_trade_like_events": events / 2,
        },
        "source_replay_lineage_guard": {"failed": lineage_failed},
    }


def test_full_walk_forward_gate_promotes_small_return_tradeoff_with_more_events() -> None:
    report = build_full_walk_forward_gate_report(
        _report(compounded=100.0, drawdown=10.0, positive=2, events=20),
        _report(compounded=98.0, drawdown=10.5, positive=2, events=30),
    )

    assert report["overall_status"] == "activity_tradeoff"
    assert report["decision"] == "eligible_for_paper_evidence_collection_only"
    assert report["promotion_type"] == "activity_tradeoff"
    assert report["deltas"]["total_trade_like_events"] == 10


def test_full_walk_forward_gate_marks_no_delta_candidate_as_neutral_equivalent() -> None:
    report = build_full_walk_forward_gate_report(
        _report(compounded=100.0, drawdown=10.0, positive=2, events=20),
        _report(compounded=100.0, drawdown=10.0, positive=2, events=20),
    )

    assert report["overall_status"] == "neutral_equivalent"
    assert report["promotion_type"] == "neutral_equivalent"
    assert report["decision"] == "do_not_replace_current_candidate_without_non_metric_reason"
    assert report["failed_checks"] == []


def test_full_walk_forward_gate_blocks_large_return_degradation_despite_more_events() -> None:
    report = build_full_walk_forward_gate_report(
        _report(compounded=100.0, drawdown=10.0, positive=2, events=20),
        _report(compounded=80.0, drawdown=10.0, positive=2, events=40),
    )

    assert report["overall_status"] == "blocked"
    assert report["decision"] == "do_not_promote_to_paper_or_live"
    assert "compounded_return_degradation" in report["failed_checks"]


def test_full_walk_forward_gate_blocks_failed_source_replay_lineage_guard() -> None:
    report = build_full_walk_forward_gate_report(
        _report(compounded=100.0, drawdown=10.0, positive=2, events=20),
        _report(compounded=100.0, drawdown=10.0, positive=2, events=20, lineage_failed=True),
    )

    assert report["overall_status"] == "blocked"
    assert "source_replay_lineage_guard_failed" in report["failed_checks"]


def test_full_walk_forward_gate_default_candidate_tracks_promoted_profitable_low_activity() -> None:
    assert "market_state_rotation_v6_imp473_profitable_low_activity_diag" in DEFAULT_CANDIDATE_REPORT
