from app.services.strategy_blueprints import build_regime_matrix, list_blueprints


def test_strategy_blueprints_include_current_anchor_and_overlay() -> None:
    keys = {item.key for item in list_blueprints()}
    assert "sweep_reversal" in keys
    assert "transition_edge_overlay" in keys
    assert "capital_preservation_no_trade" in keys
    assert "nanyotti_rotation_method_overlay" in keys


def test_strategy_blueprints_transition_matrix_contains_current_families() -> None:
    matrix = build_regime_matrix()
    assert "sweep_reversal" in matrix["transition"]
    assert "transition_edge_overlay" in matrix["transition"]


def test_strategy_blueprints_can_filter_by_lifecycle_and_regime() -> None:
    research_keys = {item.key for item in list_blueprints(lifecycle="research")}
    assert "choch_displacement_reclaim" in research_keys
    assert "orb_breakout" in research_keys

    trend_keys = {item.key for item in list_blueprints(regime="trend")}
    assert "liquidity_run_continuation" in trend_keys
    assert "volatility_expansion" in trend_keys
    assert "session_auction_reclaim" in trend_keys
