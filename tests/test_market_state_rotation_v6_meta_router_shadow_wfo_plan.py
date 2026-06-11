from datetime import UTC, datetime

from scripts.run_market_state_rotation_v6_meta_router_shadow_wfo_plan import (
    build_meta_router_shadow_wfo_plan,
)


def _meta_router_audit() -> dict:
    return {
        "status": "adaptive_meta_router_audit_complete",
        "input_walk_forward_report": "reports/current_walk.json",
        "next_experiment_order": [
            {"id": "router_contract_shadow_wfo", "enabled": True},
            {"id": "one_way_runner_protection_ablation", "enabled": True},
            {"id": "negative_base_context_pruning_ablation", "enabled": False},
            {"id": "paper_execution_parity_collection", "enabled": True},
        ],
    }


def test_meta_router_shadow_wfo_plan_builds_research_only_commands_from_audit() -> None:
    report = build_meta_router_shadow_wfo_plan(
        meta_router_audit=_meta_router_audit(),
        fold_limit=1,
        fold_offset=15,
        test_top_train_candidates=1,
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )
    recipes = {item["id"]: item for item in report["recipes"]}

    assert report["no_live_order_sent"] is True
    assert report["safety_policy"]["paper_or_live_execution"] is False
    assert report["source_report"] == "reports/current_walk.json"
    assert report["enabled_recipe_count"] == 15
    assert recipes["router_contract_observe_only"]["enabled"] is True
    assert recipes["router_contract_conservative"]["enabled"] is True
    assert recipes["mode_loss_abstain_soft"]["enabled"] is True
    assert recipes["selective_mode_loss_after_selection"]["enabled"] is True
    assert recipes["selective_mode_loss_after_selection_light"]["enabled"] is True
    assert recipes["one_way_trim_tax_light"]["enabled"] is True
    assert recipes["one_way_runner_protection"]["enabled"] is True
    assert recipes["trend_reaction_boost_only"]["enabled"] is True
    assert recipes["capacity_rebalance_150"]["enabled"] is True
    assert recipes["capacity_split_150"]["enabled"] is True
    assert recipes["capacity_split_200"]["enabled"] is True
    assert recipes["winner_pyramid_no_prune_110"]["enabled"] is True
    assert recipes["winner_pyramid_no_prune_115"]["enabled"] is True
    assert recipes["winner_pyramid_no_prune_125"]["enabled"] is True
    assert recipes["winner_refill_after_trim_100_r010_s4"]["enabled"] is True
    assert recipes["negative_base_context_pruning"]["enabled"] is False
    for recipe in report["recipes"]:
        command = recipe["command"]
        assert command[:2] == [
            ".venv/bin/python",
            "scripts/run_market_state_rotation_v6_walk_forward_validation.py",
        ]
        assert "--regime-router-enabled" in command
        assert "--fold-limit" in command
        assert "--fold-offset" in command
        assert "--warm-fold-offset-selection-state" not in command
        assert "--disable-source-replay-auto-warm-selection-state" in command
        assert "--source-replay-watch-unresolved-material-drift" in command
        assert "--write-report" in command
        assert "live" not in " ".join(command).lower()
    observe_command = recipes["router_contract_observe_only"]["command"]
    assert "--router-transition-trim-fraction" not in observe_command
    assert observe_command[observe_command.index("--router-one-way-counter-size-mult") + 1] == "1.0"
    assert observe_command[observe_command.index("--router-range-base-size-mult") + 1] == "1.0"
    trend_command = recipes["trend_reaction_boost_only"]["command"]
    assert trend_command[trend_command.index("--router-trend-reaction-size-mult") + 1] == "1.15"
    capacity_command = recipes["capacity_rebalance_150"]["command"]
    assert "--exposure-rebalance-after-selection" in capacity_command
    assert (
        capacity_command[
            capacity_command.index("--exposure-rebalance-after-selection-max-possible-units") + 1
        ]
        == "1.5"
    )
    split_mid_command = recipes["capacity_split_150"]["command"]
    assert "--exposure-rebalance-after-selection" in split_mid_command
    assert (
        split_mid_command[
            split_mid_command.index("--exposure-rebalance-after-selection-max-possible-units") + 1
        ]
        == "1.5"
    )
    assert (
        split_mid_command[
            split_mid_command.index("--exposure-rebalance-after-selection-base-add-units") + 1
        ]
        == "1.0"
    )
    assert (
        split_mid_command[
            split_mid_command.index("--exposure-rebalance-after-selection-battle-units") + 1
        ]
        == "0.5"
    )
    split_command = recipes["capacity_split_200"]["command"]
    assert "--exposure-rebalance-after-selection" in split_command
    assert (
        split_command[
            split_command.index("--exposure-rebalance-after-selection-max-possible-units") + 1
        ]
        == "2.0"
    )
    assert (
        split_command[
            split_command.index("--exposure-rebalance-after-selection-base-add-units") + 1
        ]
        == "1.0"
    )
    assert (
        split_command[
            split_command.index("--exposure-rebalance-after-selection-battle-units") + 1
        ]
        == "0.5"
    )
    selective_trim_command = recipes["selective_mode_loss_after_selection"]["command"]
    assert "--router-mode-size-after-selection" in selective_trim_command
    assert (
        selective_trim_command[
            selective_trim_command.index(
                "--router-mode-size-after-selection-trend-reaction-size-mult"
            )
            + 1
        ]
        == "0.50"
    )
    assert (
        selective_trim_command[
            selective_trim_command.index(
                "--router-mode-size-after-selection-one-way-counter-size-mult"
            )
            + 1
        ]
        == "0.0"
    )
    assert (
        selective_trim_command[
            selective_trim_command.index(
                "--router-mode-size-after-selection-min-train-return-pct"
            )
            + 1
        ]
        == "230"
    )
    selective_light_command = recipes["selective_mode_loss_after_selection_light"]["command"]
    assert "--router-mode-size-after-selection" in selective_light_command
    assert (
        selective_light_command[
            selective_light_command.index(
                "--router-mode-size-after-selection-trend-reaction-size-mult"
            )
            + 1
        ]
        == "0.70"
    )
    assert (
        selective_light_command[
            selective_light_command.index(
                "--router-mode-size-after-selection-range-probe-size-mult"
            )
            + 1
        ]
        == "0.75"
    )
    winner_pyramid_command = recipes["winner_pyramid_no_prune_110"]["command"]
    assert winner_pyramid_command[winner_pyramid_command.index("--winner-pyramid-max-units") + 1] == "1.10"
    assert (
        winner_pyramid_command[
            winner_pyramid_command.index("--exposure-rebalance-after-selection-max-possible-units") + 1
        ]
        == "1.10"
    )
    refill_command = recipes["winner_refill_after_trim_100_r010_s4"]["command"]
    assert "--exposure-rebalance-after-selection" not in refill_command
    assert refill_command[refill_command.index("--winner-pyramid-units") + 1] == "0.25"
    assert refill_command[refill_command.index("--winner-pyramid-min-profit-reaction") + 1] == "0.10"
    assert refill_command[refill_command.index("--winner-pyramid-min-score") + 1] == "4"
    assert refill_command[refill_command.index("--winner-pyramid-min-reason-stack") + 1] == "1"
    assert refill_command[refill_command.index("--winner-pyramid-max-units") + 1] == "1.0"
    probe_command = recipes["probe_alpha_leak_pruning"]["command"]
    assert probe_command[probe_command.index("--near-miss-probe-units") + 1] == "0.00025"
    assert probe_command[probe_command.index("--near-miss-probe-min-score") + 1] == "4"
    assert probe_command[probe_command.index("--near-miss-probe-min-score-edge") + 1] == "2"
    assert probe_command[probe_command.index("--near-miss-probe-min-reason-stack") + 1] == "2"
    assert probe_command[probe_command.index("--near-miss-probe-max-extension-atr") + 1] == "1.5"
    assert probe_command[probe_command.index("--near-miss-probe-allowed-soft-reasons") + 1] == (
        "MC12_low_confluence"
    )


def test_meta_router_shadow_wfo_plan_enables_all_recipes_without_audit_gate() -> None:
    report = build_meta_router_shadow_wfo_plan(
        meta_router_audit=None,
        source_report="reports/manual_source.json",
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    assert report["enabled_recipe_count"] == report["recipe_count"]
    assert report["enabled_experiment_ids_from_audit"] == []
    assert {item["id"] for item in report["recipes"]} == {
        "router_contract_observe_only",
        "router_contract_conservative",
        "mode_loss_abstain_soft",
        "selective_mode_loss_after_selection",
        "selective_mode_loss_after_selection_light",
        "one_way_trim_tax_light",
        "one_way_runner_protection",
        "trend_reaction_boost_only",
        "capacity_rebalance_150",
        "capacity_split_150",
        "capacity_split_200",
        "winner_pyramid_no_prune_110",
        "winner_pyramid_no_prune_115",
        "winner_pyramid_no_prune_125",
        "winner_refill_after_trim_100_r010_s4",
        "negative_base_context_pruning",
        "probe_alpha_leak_pruning",
        "winner_only_capacity",
    }


def test_meta_router_shadow_wfo_plan_can_preserve_warm_selection_state_for_formal_runs() -> None:
    report = build_meta_router_shadow_wfo_plan(
        meta_router_audit=_meta_router_audit(),
        fold_limit=1,
        fold_offset=15,
        warm_fold_offset_selection_state=True,
        disable_source_replay_auto_warm_selection_state=False,
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    assert report["warm_fold_offset_selection_state"] is True
    assert report["disable_source_replay_auto_warm_selection_state"] is False
    assert "--warm-fold-offset-selection-state" in report["recipes"][0]["command"]
    assert "--disable-source-replay-auto-warm-selection-state" not in report["recipes"][0]["command"]
