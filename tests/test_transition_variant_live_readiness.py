from app.services.transition_variant_live_readiness import evaluate_transition_variant_live_readiness


def test_transition_variant_live_readiness_waits_without_shadow_passes() -> None:
    readiness = evaluate_transition_variant_live_readiness(
        symbol="BTCUSDC",
        dashboard_payload={
            "active_contract": {
                "transition_edge_variant_shadow": {
                    "shadow_evaluated_count": 44,
                    "shadow_pass_count": 0,
                    "shadow_pass_rate": 0.0,
                    "shadow_candidate_delta": 0,
                    "low_confluence_block_delta": 0,
                    "expected_ev_r_proxy": 0.0,
                    "shadow_rescue_reason_mix": {},
                }
            }
        },
        safety_payload={
            "transition_edge_variant": {
                "enabled": True,
                "shadow_only": True,
                "killed": False,
                "live_lane": {"counts": {"base": {"intent": 0}, "variant": {"intent": 0}}},
            }
        },
    )
    assert readiness.status == "waiting_shadow_signal"
    assert readiness.ready_for_partial is False
    assert "shadow_pass_count_below_minimum" in readiness.blockers


def test_transition_variant_live_readiness_can_mark_ready_for_partial() -> None:
    readiness = evaluate_transition_variant_live_readiness(
        symbol="ETHUSDC",
        dashboard_payload={
            "active_contract": {
                "transition_edge_variant_shadow": {
                    "shadow_evaluated_count": 12,
                    "shadow_pass_count": 3,
                    "shadow_pass_rate": 0.25,
                    "shadow_candidate_delta": 3,
                    "low_confluence_block_delta": -3,
                    "expected_ev_r_proxy": 0.22,
                    "shadow_rescue_reason_mix": {"one_bar_shadow": 2, "proof_reclaim_shadow": 1},
                }
            }
        },
        safety_payload={
            "transition_edge_variant": {
                "enabled": True,
                "shadow_only": True,
                "killed": False,
                "live_lane": {"counts": {"base": {"intent": 1}, "variant": {"intent": 0}}},
            }
        },
    )
    assert readiness.status == "shadow_ready_for_partial"
    assert readiness.ready_for_partial is True
    assert readiness.blockers == ()


def test_transition_variant_live_readiness_live_enabled_keeps_shadow_scarcity_advisory() -> None:
    readiness = evaluate_transition_variant_live_readiness(
        symbol="BTCUSDC",
        dashboard_payload={
            "active_contract": {
                "transition_edge_variant_shadow": {
                    "shadow_evaluated_count": 0,
                    "shadow_pass_count": 0,
                    "shadow_pass_rate": 0.0,
                    "shadow_candidate_delta": 0,
                    "low_confluence_block_delta": 0,
                    "expected_ev_r_proxy": 0.0,
                    "shadow_rescue_reason_mix": {},
                }
            }
        },
        safety_payload={
            "transition_edge_variant": {
                "enabled": True,
                "shadow_only": False,
                "killed": False,
                "live_lane": {"counts": {"base": {"intent": 1}, "variant": {"intent": 0}}},
            }
        },
    )

    assert readiness.status == "live_observing_shadow_evidence"
    assert readiness.ready_for_partial is False
    assert readiness.blockers == ()
    assert "no_shadow_evaluations" in readiness.advisory_blockers
    assert "shadow_pass_count_below_minimum" in readiness.advisory_blockers
