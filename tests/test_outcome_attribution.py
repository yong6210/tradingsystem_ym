from __future__ import annotations

from app.services.outcome_attribution import build_outcome_attribution, summarize_outcome_attribution


def test_outcome_attribution_decomposes_closed_expected_and_realized_r() -> None:
    payload = build_outcome_attribution(
        score_to_outcome_funnel={
            "historical_execution_outcomes": {"closed": 6},
            "money_funnel": {
                "historical_expected_r": {
                    "generated": 2.5,
                    "submitted": 1.8,
                    "filled": 1.2,
                    "closed": 0.9,
                },
                "historical_realized_r": {
                    "raw_closed": 0.7,
                    "post_cost_closed": 0.6,
                    "cost_drag": -0.1,
                },
                "historical_gap_r": {
                    "submitted_to_filled": 0.6,
                },
                "summary": "expected_closed_r=0.9000, post_cost_closed_r=0.6000, submitted_to_filled_gap_r=0.6000",
            },
        },
        execution_friction_measurement={"friction_state": "watch_friction", "weakest_axis": "slippage_state"},
    )

    assert payload is not None
    assert payload["strategy_component_r"] == 0.9
    assert payload["execution_component_r"] == -0.1
    assert payload["condition_component_r"] == -0.2
    assert payload["fill_capture_gap_r"] == 0.6
    assert payload["strongest_drag_source"] == "fill_capture_gap"

    summary = summarize_outcome_attribution(payload)

    assert summary is not None
    assert summary["closed_post_cost_delta_r"] == -0.3
    assert summary["source_summary"]["weakest_execution_axis"] == "slippage_state"
