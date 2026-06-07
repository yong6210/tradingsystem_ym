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
    assert report["enabled_recipe_count"] == 5
    assert recipes["router_contract_observe_only"]["enabled"] is True
    assert recipes["router_contract_conservative"]["enabled"] is True
    assert recipes["mode_loss_abstain_soft"]["enabled"] is True
    assert recipes["one_way_trim_tax_light"]["enabled"] is True
    assert recipes["one_way_runner_protection"]["enabled"] is True
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
        "one_way_trim_tax_light",
        "one_way_runner_protection",
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
