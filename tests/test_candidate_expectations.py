from __future__ import annotations

from app.services.candidate_expectations import block_reason_message, expectation_contract


def test_expectation_contract_builds_summary_from_validity() -> None:
    payload = expectation_contract(
        validity={
            "expected_win_prob": 0.5821,
            "expected_ev_r": 0.2149,
            "expected_tp1_prob": 0.71,
            "expected_tp2_prob": 0.48,
            "expected_tp3_prob": 0.27,
        },
        ev=0.0,
        recommended_risk_r=0.5,
    )

    assert payload["expected_win_prob"] == 0.5821
    assert payload["expected_ev_r"] == 0.2149
    assert payload["expected_ev_at_recommended_size_r"] == 0.1075
    assert "win≈58.2%" in payload["expected_summary"]
    assert "EV≈+0.21R" in payload["expected_summary"]


def test_block_reason_message_maps_known_reason() -> None:
    assert (
        block_reason_message("thesis_cluster_cap_zero_risk")
        == "Blocked: thesis cluster cap already consumes all allocatable risk."
    )
