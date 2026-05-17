from __future__ import annotations

from app.core.config import get_settings
from app.core.enums import StrategyMode
from app.services.strategy_mode import StrategyModeService


def test_strategy_mode_policy_defaults_to_a_only() -> None:
    settings = get_settings()
    old_mode = settings.strategy_mode
    old_daily_trades = settings.strategy_mode_a_only_max_daily_trades
    old_total_risk = settings.strategy_mode_a_only_max_total_risk_r
    try:
        settings.strategy_mode = StrategyMode.A_ONLY
        settings.strategy_mode_a_only_max_daily_trades = 3
        settings.strategy_mode_a_only_max_total_risk_r = 1.5
        service = StrategyModeService(settings)
        policy = service.policy()
        assert policy.mode == StrategyMode.A_ONLY
        assert policy.allowed_grades == ("A",)
        assert "sweep_reversal" in policy.allowed_families
        assert policy.max_daily_trades == 3
        assert policy.max_total_risk_r == 1.5
    finally:
        settings.strategy_mode = old_mode
        settings.strategy_mode_a_only_max_daily_trades = old_daily_trades
        settings.strategy_mode_a_only_max_total_risk_r = old_total_risk


def test_strategy_mode_policy_tolerates_malformed_numeric_settings() -> None:
    settings = get_settings().model_copy(deep=True)
    settings.strategy_mode = StrategyMode.A_ONLY
    settings.strategy_mode_a_only_max_daily_trades = "inf"
    settings.strategy_mode_a_only_max_total_risk_r = "bad-risk"

    policy = StrategyModeService(settings).policy()

    assert policy.max_daily_trades == 3
    assert policy.max_total_risk_r == 1.5


def test_strategy_mode_research_zeroes_live_risk() -> None:
    settings = get_settings()
    old_mode = settings.strategy_mode
    try:
        settings.strategy_mode = StrategyMode.RESEARCH
        service = StrategyModeService(settings)
        sizing = service.apply_to_sizing(
            {
                "final_risk_r": 0.5,
                "blocked": False,
                "blocked_reason": None,
                "notes": {},
            }
        )
        assert sizing["strategy_mode"] == "RESEARCH"
        assert sizing["shadow_only"] is True
        assert sizing["final_risk_r"] == 0.0
        assert sizing["blocked"] is True
        assert sizing["blocked_reason"] == "mode_shadow_only"
    finally:
        settings.strategy_mode = old_mode
