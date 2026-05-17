from app.services.micro_main_live_readiness import evaluate_micro_main_live_readiness
from app.services.micro_main_universe_policy import build_micro_main_universe_policy_snapshot


def test_micro_main_live_readiness_waits_without_recent_setup() -> None:
    readiness = evaluate_micro_main_live_readiness(
        symbol="BTCUSDC",
        shadow_summary={
            "available": True,
            "decision": "REJECT",
            "recent_closed": 0,
            "ev_r": 0.0,
            "total_r": 0.0,
        },
        universe_policy=build_micro_main_universe_policy_snapshot(),
        enabled=True,
        shadow_only=True,
        partial_ratio=0.3,
        core_live_slots=2,
        secondary_live_enabled=False,
    )
    assert readiness.status == "waiting_fresh_setup"
    assert readiness.ready_for_partial is False
    assert "no_recent_closed_sample" in readiness.blockers


def test_micro_main_live_readiness_respects_core_rollout_window() -> None:
    readiness = evaluate_micro_main_live_readiness(
        symbol="SOLUSDC",
        shadow_summary={
            "available": True,
            "decision": "PASS",
            "recent_closed": 24,
            "ev_r": 0.42,
            "total_r": 10.1,
        },
        universe_policy=build_micro_main_universe_policy_snapshot(),
        enabled=True,
        shadow_only=True,
        partial_ratio=0.3,
        core_live_slots=2,
        secondary_live_enabled=False,
    )
    assert readiness.status == "outside_current_core_live_window"
    assert readiness.ready_for_partial is False
    assert "outside_current_core_live_window" in readiness.blockers


def test_micro_main_live_readiness_can_mark_core_symbol_ready() -> None:
    readiness = evaluate_micro_main_live_readiness(
        symbol="ETHUSDC",
        shadow_summary={
            "available": True,
            "decision": "PASS",
            "recent_closed": 28,
            "ev_r": 0.61,
            "total_r": 17.08,
            "win_rate": 0.64,
        },
        universe_policy=build_micro_main_universe_policy_snapshot(),
        enabled=True,
        shadow_only=True,
        partial_ratio=0.3,
        core_live_slots=2,
        secondary_live_enabled=False,
    )
    assert readiness.status == "shadow_ready_for_partial"
    assert readiness.ready_for_partial is True
    assert readiness.blockers == ()


def test_micro_main_live_readiness_secondary_symbol_stays_shadow_only_even_when_global_shadow_only_is_false() -> None:
    readiness = evaluate_micro_main_live_readiness(
        symbol="SUIUSDC",
        shadow_summary={
            "available": True,
            "decision": "REJECT",
            "recent_closed": 0,
            "ev_r": 0.0,
            "total_r": 0.0,
        },
        universe_policy=build_micro_main_universe_policy_snapshot(),
        enabled=True,
        shadow_only=False,
        partial_ratio=0.3,
        core_live_slots=11,
        secondary_live_enabled=False,
    )
    assert readiness.status == "secondary_shadow_only"
    assert readiness.ready_for_partial is False
    assert "secondary_rollout_disabled" in readiness.blockers


def test_micro_main_live_readiness_core_symbol_without_recent_sample_bootstraps_live_canary() -> None:
    readiness = evaluate_micro_main_live_readiness(
        symbol="BTCUSDC",
        shadow_summary={
            "available": True,
            "decision": "REJECT",
            "recent_closed": 0,
            "ev_r": 0.0,
            "total_r": 0.0,
        },
        universe_policy=build_micro_main_universe_policy_snapshot(),
        enabled=True,
        shadow_only=False,
        partial_ratio=0.3,
        core_live_slots=11,
        secondary_live_enabled=False,
    )
    assert readiness.status == "live_bootstrap_collecting"
    assert readiness.ready_for_partial is False
    assert readiness.blockers == ()
    assert "no_recent_closed_sample" in readiness.advisory_blockers
    assert "shadow_decision_not_pass" not in readiness.advisory_blockers


def test_micro_main_live_readiness_core_slots_count_core_symbols_only() -> None:
    readiness = evaluate_micro_main_live_readiness(
        symbol="NEARUSDC",
        shadow_summary={
            "available": True,
            "decision": "REJECT",
            "recent_closed": 0,
            "ev_r": 0.0,
            "total_r": 0.0,
        },
        universe_policy=build_micro_main_universe_policy_snapshot(),
        enabled=True,
        shadow_only=False,
        partial_ratio=1.0,
        core_live_slots=11,
        secondary_live_enabled=False,
    )

    assert readiness.status == "live_bootstrap_collecting"
    assert readiness.blockers == ()
    assert readiness.shadow_metrics["core_live_rank"] == 11


def test_micro_main_live_readiness_ranks_usdt_rollout_window_separately_from_usdc() -> None:
    readiness = evaluate_micro_main_live_readiness(
        symbol="DASHUSDT",
        shadow_summary={
            "available": True,
            "decision": "REJECT",
            "recent_closed": 0,
            "ev_r": 0.0,
            "total_r": 0.0,
        },
        universe_policy=build_micro_main_universe_policy_snapshot(),
        enabled=True,
        shadow_only=False,
        partial_ratio=1.0,
        core_live_slots=31,
        secondary_live_enabled=False,
    )

    assert readiness.status == "live_bootstrap_collecting"
    assert readiness.blockers == ()
    assert readiness.shadow_metrics["core_live_rank"] == 31
