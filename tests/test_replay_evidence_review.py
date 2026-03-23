from __future__ import annotations

from pathlib import Path

from app.services.replay_evidence_review import ReplayEvidenceReviewService


def test_replay_evidence_review_marks_validated_replay_as_context_only_support(tmp_path: Path) -> None:
    service = ReplayEvidenceReviewService()
    service.settings.replay_evidence_review_report_dir = str(tmp_path)

    payload = service.summarize(
        symbol="BTCUSDC",
        version="v2",
        days=180,
        a_review={
            "edge_state": "validated_edge",
            "analysis_bias": "keep_anchor",
            "target_metrics": {"trades": 12},
            "next_actions": ["keep_a"],
        },
        b_review={
            "edge_state": "fragile_edge",
            "analysis_bias": "monitor_diversification",
            "target_metrics": {"trades": 8},
            "next_actions": ["keep_b_guarded"],
        },
        replay_lineage={
            "available": True,
            "runtime_inputs_ready": True,
            "reason": "runtime_lineage_ready",
            "coverage": {"execution_fill_coverage": 0.9},
            "blocked_by": [],
            "next_steps": ["prototype replay ready"],
        },
        replay_assessment={
            "available": True,
            "full_replay_ready": True,
            "replacement_recommended": False,
            "reason": "approximation_sufficient_for_now",
            "sample_counts": {"eligible_closed_trades": 18},
            "coverage": {"execution_fill_coverage": 0.9},
            "deployment_recommendation": {"decision": "keep_approximation"},
            "next_steps": ["keep approximation"],
        },
        write_report=True,
    )

    assert payload["confidence_state"] == "validated_replay_evidence"
    assert payload["evidence_bias"] == "combine_with_live_evidence"
    assert payload["do_not_treat_as_live_confidence"] is True
    report_path = Path(str(payload["report_path"]))
    assert report_path.exists()
    body = report_path.read_text(encoding="utf-8")
    assert "## Replay Lineage" in body
    assert "## Replay Assessment" in body


def test_replay_evidence_review_marks_missing_lineage_as_insufficient() -> None:
    service = ReplayEvidenceReviewService()

    payload = service.summarize(
        symbol="BTCUSDC",
        version="v2",
        days=180,
        a_review={
            "edge_state": "validated_edge",
            "analysis_bias": "keep_anchor",
            "target_metrics": {"trades": 12},
            "next_actions": [],
        },
        b_review={
            "edge_state": "validated_edge",
            "analysis_bias": "support_guarded_activation",
            "target_metrics": {"trades": 10},
            "next_actions": [],
        },
        replay_lineage={
            "available": True,
            "runtime_inputs_ready": False,
            "reason": "runtime_lineage_incomplete",
            "coverage": {},
            "blocked_by": ["latency_candle_coverage_below_threshold"],
            "next_steps": ["improve candle retention"],
        },
        replay_assessment={
            "available": True,
            "full_replay_ready": False,
            "replacement_recommended": False,
            "reason": "insufficient_runtime_lineage",
            "sample_counts": {"eligible_closed_trades": 18},
            "coverage": {},
            "deployment_recommendation": {"decision": "keep_approximation"},
            "next_steps": ["improve lineage"],
        },
        write_report=False,
    )

    assert payload["confidence_state"] == "insufficient_replay_lineage"
    assert payload["evidence_bias"] == "gather_more_replay_evidence"
