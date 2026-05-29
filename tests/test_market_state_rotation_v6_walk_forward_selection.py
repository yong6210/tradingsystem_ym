from scripts.run_market_state_rotation_v6_walk_forward_validation import _selection_score


def test_structural_flag_penalty_allows_zero_min_train_return() -> None:
    result = {
        "score": 1.0,
        "total_return_pct": 12.0,
        "max_drawdown_pct": 10.0,
        "estimated_cost_drag_pct": 0.0,
        "event_diagnostics": {
            "flags": ["one_way_forced_trim_overuse", "high_turnover_per_add"],
            "ratios": {},
        },
    }

    score = _selection_score(
        result,
        flag_penalty=0.0,
        structural_flag_min_train_return_pct=0.0,
        structural_flag_penalty=0.05,
    )

    assert score == 0.9


def test_high_train_flag_penalty_only_applies_above_return_threshold() -> None:
    result = {
        "score": 1.0,
        "total_return_pct": 125.0,
        "max_drawdown_pct": 10.0,
        "estimated_cost_drag_pct": 0.0,
        "event_diagnostics": {
            "flags": ["side_imbalance", "probe_overuse"],
            "ratios": {},
        },
    }

    penalized = _selection_score(
        result,
        flag_penalty=0.0,
        high_train_flag_min_return_pct=100.0,
        high_train_flag_penalty=0.15,
    )
    unpenalized = _selection_score(
        {**result, "total_return_pct": 95.0},
        flag_penalty=0.0,
        high_train_flag_min_return_pct=100.0,
        high_train_flag_penalty=0.15,
    )

    assert penalized == 0.7
    assert unpenalized == 1.0
