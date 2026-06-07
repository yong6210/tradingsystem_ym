from dataclasses import replace
import json
from pathlib import Path

from scripts.run_market_state_rotation_v6_backtest import MarketStateConfig
from scripts.run_market_state_rotation_v6_walk_forward_validation import _material_config_key


def _base_config() -> MarketStateConfig:
    report = json.loads(
        Path(
            "reports/validation/diagnostics/market_state_rotation_v6_imp490_current_top_candidate_audit/"
            "market_state_rotation_v6_walk_forward_BTCUSDT_5m_latest.json"
        ).read_text(encoding="utf-8")
    )
    return MarketStateConfig(**report["folds"][0]["selected_train_result"]["config"])


def test_material_key_can_treat_observe_only_router_as_source_replay_equivalent() -> None:
    base = _base_config()
    observe_only = replace(
        base,
        model_id="router",
        regime_router_enabled=True,
        router_trend_reaction_size_mult=1.0,
        router_one_way_chase_size_mult=1.0,
        router_one_way_counter_size_mult=1.0,
        router_range_probe_size_mult=1.0,
        router_range_base_size_mult=1.0,
        router_exhaustion_reversal_size_mult=1.0,
        router_risk_off_size_mult=1.0,
        router_transition_trim_fraction=0.0,
        router_transition_trim_modes=(),
    )

    assert _material_config_key(base) != _material_config_key(observe_only)
    assert _material_config_key(base, ignore_observe_only_router=True) == _material_config_key(
        observe_only,
        ignore_observe_only_router=True,
    )


def test_material_key_does_not_hide_active_router_sizing_changes() -> None:
    base = _base_config()
    active_router = replace(
        base,
        model_id="router",
        regime_router_enabled=True,
        router_trend_reaction_size_mult=1.0,
        router_one_way_chase_size_mult=1.0,
        router_one_way_counter_size_mult=0.0,
        router_range_probe_size_mult=1.0,
        router_range_base_size_mult=1.0,
        router_exhaustion_reversal_size_mult=1.0,
        router_risk_off_size_mult=1.0,
    )

    assert _material_config_key(base, ignore_observe_only_router=True) != _material_config_key(
        active_router,
        ignore_observe_only_router=True,
    )
