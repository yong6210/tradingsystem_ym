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
    folds: list[dict] | None = None,
) -> dict:
    return {
        "folds": folds if folds is not None else [{}] * 2,
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


def test_full_walk_forward_gate_reports_fold_level_failure_details() -> None:
    baseline = _report(
        compounded=100.0,
        drawdown=3.0,
        positive=2,
        events=10,
        folds=[
            {
                "fold": 1,
                "test_start": "2024-01-01",
                "test_end": "2024-01-31",
                "test_result": {
                    "total_return_pct": 10.0,
                    "max_drawdown_pct": 2.0,
                    "trade_like_events": 5,
                    "event_diagnostics": {"add_by_role": {"base": 5}},
                },
            },
            {
                "fold": 2,
                "test_start": "2024-02-01",
                "test_end": "2024-02-29",
                "test_result": {
                    "total_return_pct": 20.0,
                    "max_drawdown_pct": 3.0,
                    "trade_like_events": 5,
                    "event_diagnostics": {"add_by_role": {"base": 5}},
                },
            },
        ],
    )
    candidate = _report(
        compounded=80.0,
        drawdown=9.0,
        positive=1,
        events=13,
        folds=[
            {
                "fold": 1,
                "test_start": "2024-01-01",
                "test_end": "2024-01-31",
                "test_result": {
                    "total_return_pct": 12.0,
                    "max_drawdown_pct": 1.5,
                    "trade_like_events": 6,
                    "event_diagnostics": {"add_by_role": {"base": 4, "probe": 2}},
                },
            },
            {
                "fold": 2,
                "test_start": "2024-02-01",
                "test_end": "2024-02-29",
                "test_result": {
                    "total_return_pct": -1.0,
                    "max_drawdown_pct": 9.0,
                    "trade_like_events": 7,
                    "event_diagnostics": {"add_by_role": {"base": 3, "probe": 4}},
                },
            },
        ],
    )

    report = build_full_walk_forward_gate_report(baseline, candidate)

    summary = report["fold_delta_summary"]
    assert summary["matched_fold_count"] == 2
    assert summary["return_degraded_fold_count"] == 1
    assert summary["positive_fold_lost_count"] == 1
    assert summary["positive_fold_lost_ids"] == ["2"]
    assert summary["drawdown_gate_violation_fold_ids"] == ["2"]
    assert summary["total_candidate_probe_adds"] == 6
    assert summary["worst_return_degradation_fold"]["fold"] == "2"
    assert summary["worst_return_degradation_fold"]["return_delta_pct"] == -21.0
    assert report["failure_details"]["drawdown_worsening"]["worst_fold"]["fold"] == "2"
    assert "candidate_turns_previously_positive_oos_folds_negative" in report["root_cause_hints"]
    assert report["activity_regression_summary"]["signal_sparsity_fix_failed"] is False
    assert report["fold_deltas"][1]["candidate_add_by_role"]["probe"] == 4


def test_full_walk_forward_gate_flags_probe_activity_regression_as_signal_sparsity_failure() -> None:
    baseline = _report(
        compounded=100.0,
        drawdown=3.0,
        positive=2,
        events=12,
        folds=[
            {
                "fold": 1,
                "test_result": {
                    "total_return_pct": 8.0,
                    "max_drawdown_pct": 2.0,
                    "trade_like_events": 6,
                    "event_diagnostics": {"add_by_role": {"base": 2, "probe": 4}},
                },
            },
            {
                "fold": 2,
                "test_result": {
                    "total_return_pct": 9.0,
                    "max_drawdown_pct": 3.0,
                    "trade_like_events": 6,
                    "event_diagnostics": {"add_by_role": {"base": 2, "probe": 4}},
                },
            },
        ],
    )
    candidate = _report(
        compounded=80.0,
        drawdown=8.0,
        positive=1,
        events=5,
        folds=[
            {
                "fold": 1,
                "test_result": {
                    "total_return_pct": 7.0,
                    "max_drawdown_pct": 2.5,
                    "trade_like_events": 3,
                    "event_diagnostics": {"add_by_role": {"base": 2, "probe": 1}},
                },
            },
            {
                "fold": 2,
                "test_result": {
                    "total_return_pct": -4.0,
                    "max_drawdown_pct": 8.0,
                    "trade_like_events": 2,
                    "event_diagnostics": {"add_by_role": {"base": 2}},
                },
            },
        ],
    )

    report = build_full_walk_forward_gate_report(baseline, candidate)

    activity = report["activity_regression_summary"]
    assert activity["baseline_probe_adds"] == 8
    assert activity["candidate_probe_adds"] == 1
    assert activity["probe_add_delta"] == -7
    assert activity["trade_like_events_delta"] == -7
    assert activity["probe_activity_regressed"] is True
    assert activity["trade_like_activity_regressed"] is True
    assert activity["signal_sparsity_fix_failed"] is True
    assert activity["probe_add_regression_fold_ids"] == ["1", "2"]
    assert "candidate_reduces_probe_activity_instead_of_solving_signal_sparsity" in report["root_cause_hints"]
    assert "candidate_reduces_total_trade_like_events" in report["root_cause_hints"]
    assert "activity_regression" in report["failure_details"]


def test_full_walk_forward_gate_can_require_nonregressing_activity_for_signal_candidates() -> None:
    baseline = _report(
        compounded=100.0,
        drawdown=3.0,
        positive=2,
        events=12,
        folds=[
            {
                "fold": 1,
                "test_result": {
                    "total_return_pct": 8.0,
                    "max_drawdown_pct": 2.0,
                    "trade_like_events": 6,
                    "event_diagnostics": {"add_by_role": {"base": 2, "probe": 4}},
                },
            },
            {
                "fold": 2,
                "test_result": {
                    "total_return_pct": 9.0,
                    "max_drawdown_pct": 3.0,
                    "trade_like_events": 6,
                    "event_diagnostics": {"add_by_role": {"base": 2, "probe": 4}},
                },
            },
        ],
    )
    candidate = _report(
        compounded=100.0,
        drawdown=3.0,
        positive=2,
        events=8,
        folds=[
            {
                "fold": 1,
                "test_result": {
                    "total_return_pct": 8.0,
                    "max_drawdown_pct": 2.0,
                    "trade_like_events": 4,
                    "event_diagnostics": {"add_by_role": {"base": 3, "probe": 1}},
                },
            },
            {
                "fold": 2,
                "test_result": {
                    "total_return_pct": 9.0,
                    "max_drawdown_pct": 3.0,
                    "trade_like_events": 4,
                    "event_diagnostics": {"add_by_role": {"base": 3, "probe": 1}},
                },
            },
        ],
    )

    diagnostic_only = build_full_walk_forward_gate_report(baseline, candidate)
    strict_signal_candidate = build_full_walk_forward_gate_report(
        baseline,
        candidate,
        require_nonregressing_activity=True,
    )

    assert diagnostic_only["failed_checks"] == []
    assert diagnostic_only["activity_regression_summary"]["signal_sparsity_fix_failed"] is True
    assert diagnostic_only["gates"]["require_nonregressing_activity"] is False
    assert strict_signal_candidate["overall_status"] == "blocked"
    assert strict_signal_candidate["decision"] == "do_not_promote_to_paper_or_live"
    assert strict_signal_candidate["gates"]["require_nonregressing_activity"] is True
    assert "activity_regression_blocks_signal_sparsity_fix" in strict_signal_candidate["failed_checks"]
    assert strict_signal_candidate["failure_details"]["activity_regression"]["probe_add_delta"] == -6


def test_full_walk_forward_gate_requires_trade_like_activity_increase_for_signal_fix() -> None:
    baseline = _report(
        compounded=100.0,
        drawdown=3.0,
        positive=2,
        events=12,
        folds=[
            {
                "fold": 1,
                "test_result": {
                    "total_return_pct": 8.0,
                    "max_drawdown_pct": 2.0,
                    "trade_like_events": 6,
                    "event_diagnostics": {"add_by_role": {"base": 2, "probe": 4}},
                },
            },
            {
                "fold": 2,
                "test_result": {
                    "total_return_pct": 9.0,
                    "max_drawdown_pct": 3.0,
                    "trade_like_events": 6,
                    "event_diagnostics": {"add_by_role": {"base": 2, "probe": 4}},
                },
            },
        ],
    )
    candidate = _report(
        compounded=100.0,
        drawdown=3.0,
        positive=2,
        events=12,
        folds=[
            {
                "fold": 1,
                "test_result": {
                    "total_return_pct": 8.0,
                    "max_drawdown_pct": 2.0,
                    "trade_like_events": 6,
                    "event_diagnostics": {"add_by_role": {"base": 2, "probe": 4}},
                },
            },
            {
                "fold": 2,
                "test_result": {
                    "total_return_pct": 9.0,
                    "max_drawdown_pct": 3.0,
                    "trade_like_events": 6,
                    "event_diagnostics": {"add_by_role": {"base": 2, "probe": 4}},
                },
            },
        ],
    )

    report = build_full_walk_forward_gate_report(
        baseline,
        candidate,
        require_nonregressing_activity=True,
    )

    activity = report["activity_regression_summary"]
    assert report["overall_status"] == "blocked"
    assert "activity_regression_blocks_signal_sparsity_fix" in report["failed_checks"]
    assert activity["probe_add_delta"] == 0
    assert activity["trade_like_events_delta"] == 0
    assert activity["probe_activity_not_regressed"] is True
    assert activity["trade_like_activity_regressed"] is False
    assert activity["trade_like_activity_increased"] is False
    assert activity["trade_like_activity_increase_required"] is True
    assert activity["minimum_trade_like_events_delta_for_signal_sparsity_fix"] == 1
    assert activity["strict_signal_sparsity_fix_failure_reasons"] == [
        "trade_like_activity_did_not_increase"
    ]
    assert "candidate_does_not_increase_total_trade_like_events" in report["root_cause_hints"]
    assert report["failure_details"]["activity_regression"][
        "strict_signal_sparsity_fix_failure_reasons"
    ] == ["trade_like_activity_did_not_increase"]


def test_full_walk_forward_gate_default_candidate_tracks_promoted_profitable_low_activity() -> None:
    assert "market_state_rotation_v6_imp473_profitable_low_activity_diag" in DEFAULT_CANDIDATE_REPORT
