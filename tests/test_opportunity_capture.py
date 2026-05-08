from __future__ import annotations

from app.services.opportunity_capture import OpportunityCaptureService


def test_opportunity_capture_summarizes_blocking_heavy_runtime_to_submit() -> None:
    service = OpportunityCaptureService()

    payload = service.generate(
        score_to_outcome_funnel={
            "available": True,
            "report_window_days": 10,
            "snapshot_selection": {
                "runtime_candidates": 10,
                "accepted_candidates": 3,
                "blocked_candidates": 7,
                "accept_rate": 0.3,
                "blocked_gate_group_counts": {
                    "quality": 4,
                    "rollout": 2,
                    "structural": 1,
                },
            },
            "historical_execution_outcomes": {
                "submitted": 2,
                "filled": 2,
                "closed": 2,
                "fill_rate_from_submitted": 1.0,
                "close_rate_from_filled": 1.0,
            },
            "decomposition": {
                "family": [
                    {
                        "key": "sweep_reversal",
                        "runtime_candidates": 6,
                        "accepted_candidates": 2,
                        "blocked_candidates": 4,
                        "submitted": 1,
                        "filled": 1,
                        "closed": 1,
                        "accept_rate": 0.3333,
                        "fill_rate_from_submitted": 1.0,
                        "close_rate_from_filled": 1.0,
                    }
                ],
                "regime": [
                    {
                        "key": "range",
                        "runtime_candidates": 4,
                        "accepted_candidates": 1,
                        "blocked_candidates": 3,
                        "submitted": 0,
                        "filled": 0,
                        "closed": 0,
                        "accept_rate": 0.25,
                        "fill_rate_from_submitted": 0.0,
                        "close_rate_from_filled": 0.0,
                    }
                ],
                "session": [
                    {
                        "key": "dead_session",
                        "runtime_candidates": 3,
                        "accepted_candidates": 0,
                        "blocked_candidates": 3,
                        "submitted": 0,
                        "filled": 0,
                        "closed": 0,
                        "accept_rate": 0.0,
                        "fill_rate_from_submitted": 0.0,
                        "close_rate_from_filled": 0.0,
                    }
                ],
            },
        },
        execution_quality={
            "fill_rate": 0.95,
            "fill_events_total": 2,
        },
    )

    assert payload is not None
    assert payload["available"] is True
    assert payload["capture_rates"]["submit_rate_from_runtime"] == 0.2
    assert payload["capture_gap"]["runtime_to_submit_gap"] == 0.8
    assert payload["dominant_bottleneck"]["stage"] == "runtime_to_submit"
    assert payload["dominant_bottleneck"]["reason"] == "quality_blocking"
    assert payload["family_focus"]["key"] == "sweep_reversal"
    assert payload["regime_modifier"]["state"] == "negative"
    assert payload["session_modifier"]["state"] == "negative"
    assert "blocking" in payload["summary"]


def test_opportunity_capture_uses_selection_shortfall_when_blocked_mix_is_empty() -> None:
    service = OpportunityCaptureService()

    payload = service.generate(
        score_to_outcome_funnel={
            "available": True,
            "report_window_days": 10,
            "snapshot_selection": {
                "runtime_candidates": 0,
                "accepted_candidates": 0,
                "blocked_candidates": 0,
                "accept_rate": 0.0,
                "blocked_gate_group_counts": {},
            },
            "historical_execution_outcomes": {
                "submitted": 2,
                "filled": 2,
                "closed": 2,
                "fill_rate_from_submitted": 1.0,
                "close_rate_from_filled": 1.0,
            },
            "decomposition": {
                "family": [
                    {
                        "key": "sweep_reversal",
                        "runtime_candidates": 0,
                        "accepted_candidates": 0,
                        "blocked_candidates": 0,
                        "submitted": 2,
                        "filled": 2,
                        "closed": 2,
                        "accept_rate": 0.0,
                        "fill_rate_from_submitted": 1.0,
                        "close_rate_from_filled": 1.0,
                    }
                ],
                "regime": [],
                "session": [],
            },
        },
        execution_quality={
            "fill_rate": 1.0,
            "fill_events_total": 2,
        },
    )

    assert payload is not None
    assert payload["blocked_mix"] == {
        "quality": 0,
        "rollout": 0,
        "structural": 0,
        "safety": 0,
        "unknown": 0,
    }
    assert payload["dominant_bottleneck"]["reason"] == "selection_shortfall"
