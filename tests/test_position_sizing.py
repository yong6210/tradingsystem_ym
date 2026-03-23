from __future__ import annotations

from math import isclose

from app.core.config import get_settings
from app.core.enums import EntryModel
from app.services.position_sizing import PositionSizingInput, PositionSizingService


def test_position_sizing_full_a_grade_risk() -> None:
    service = PositionSizingService()

    result = service.evaluate(
        PositionSizingInput(
            strategy_family="trend_continuation",
            strategy_grade="A",
            regime="trend",
            reaction_classification="acceptance_confirmed",
            confirm_only=False,
            entry_model=EntryModel.LIMIT.value,
            active_thesis_clusters=0,
            transition_state="none",
        )
    )

    assert isclose(result["final_risk_r"], 1.0)
    assert result["blocked"] is False
    assert result["blocked_reason"] is None


def test_position_sizing_composes_clamps_multiplicatively() -> None:
    service = PositionSizingService()
    settings = get_settings()

    result = service.evaluate(
        PositionSizingInput(
            strategy_family="sweep_reversal",
            strategy_grade="B",
            regime="range",
            reaction_classification="rejection_tentative",
            confirm_only=True,
            entry_model=EntryModel.CONFIRM.value,
            active_thesis_clusters=1,
            transition_state="none",
        )
    )

    expected = (
        settings.sizing_grade_b_r
        * settings.sizing_regime_factor_range
        * settings.sizing_reaction_factor_confirm_only
        * settings.sizing_thesis_factor_one_active
        * settings.sizing_execution_factor_confirm
    )
    assert isclose(result["final_risk_r"], round(expected, 4))
    assert result["blocked"] is False
    assert result["notes"]["reaction"] == "confirm_only_size_clamp"
    assert result["notes"]["thesis"] == "active_thesis_size_clamp"


def test_position_sizing_zeroes_transition_watch() -> None:
    service = PositionSizingService()

    result = service.evaluate(
        PositionSizingInput(
            strategy_family="trend_continuation",
            strategy_grade="A",
            regime="trend",
            reaction_classification="acceptance_confirmed",
            confirm_only=False,
            entry_model=EntryModel.LIMIT.value,
            active_thesis_clusters=0,
            transition_state="transition_watch",
        )
    )

    assert isclose(result["final_risk_r"], 0.0)
    assert result["blocked"] is True
    assert result["blocked_reason"] == "transition_zero_risk"


def test_position_sizing_zeroes_when_thesis_cluster_cap_is_hit() -> None:
    service = PositionSizingService()

    result = service.evaluate(
        PositionSizingInput(
            strategy_family="sweep_reversal",
            strategy_grade="A",
            regime="range",
            reaction_classification="rejection_confirmed",
            confirm_only=False,
            entry_model=EntryModel.SWEEP_CONFIRM.value,
            active_thesis_clusters=2,
            transition_state="none",
        )
    )

    assert isclose(result["final_risk_r"], 0.0)
    assert result["blocked"] is True
    assert result["blocked_reason"] == "thesis_cluster_cap_zero_risk"


def test_position_sizing_zeroes_mixed_reaction() -> None:
    service = PositionSizingService()

    result = service.evaluate(
        PositionSizingInput(
            strategy_family="sweep_reversal",
            strategy_grade="B",
            regime="range",
            reaction_classification="mixed",
            confirm_only=False,
            entry_model=EntryModel.CONFIRM.value,
            active_thesis_clusters=0,
            transition_state="none",
        )
    )

    assert isclose(result["final_risk_r"], 0.0)
    assert result["blocked"] is True
    assert result["blocked_reason"] == "mixed_zero_risk"
