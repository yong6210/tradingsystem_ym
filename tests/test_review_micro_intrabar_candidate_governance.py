from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from scripts import review_micro_intrabar_candidate_governance as governance


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _contract() -> dict:
    return {
        "authority": "paper_only_no_live_authority_change",
        "live_action": "KEEP_CLOSE_ONLY",
        "live_ready": False,
        "candidate": {"symbol_count": 4},
        "paper_contract": {
            "policy_name": "volume12_body025_hour13_14_long",
            "symbols": ["BTCUSDT", "ETHUSDT", "LINKUSDT", "DOGEUSDT"],
            "live_risk_r": 0.0,
        },
    }


def _watch(state: str = "COLLECTING_SIGNALS") -> dict:
    return {
        "recommended_state": state,
        "blockers": ["candidate_signal_count_below_paper_sample_gate"],
        "unique_candidate_summary": {"count": 0},
        "base_signal_summary": {"count": 2},
        "base_signal_rejection_summary": {
            "rejected_count": 2,
            "by_filter_reason": {"direction_mismatch": 1, "setup_hour_not_allowed": 1},
        },
        "collection_estimate": {"feasibility": "TOO_SLOW_FOR_LIVE_ONLY_COLLECTION"},
    }


def _replay(state: str = "REPLAY_SUPPORTS_PAPER_ONLY_WATCH") -> dict:
    return {
        "recommended_state": state,
        "reasons": ["recent_replay_has_no_hard_blocker"],
        "matched_trade_count": 136,
        "windows": [],
    }


def _expansion(state: str = "EXPANSION_SHADOW_WATCHLIST_ONLY") -> dict:
    return {
        "recommended_state": state,
        "reasons": ["some_symbols_are_positive_but_no_broad_scope_passed"],
        "shadow_watchlist_symbols": ["SOLUSDT", "ADAUSDT"],
    }


def _expansion_shadow_review(state: str = "COLLECTING_SIGNALS") -> dict:
    return {
        "review_label": "expansion_shadow_watchlist",
        "recommended_state": state,
        "blockers": ["candidate_signal_count_below_paper_sample_gate"],
        "unique_candidate_summary": {"count": 0},
        "base_signal_summary": {"count": 1},
        "base_signal_rejection_summary": {
            "rejected_count": 1,
            "by_filter_reason": {"direction_mismatch": 1},
        },
        "collection_estimate": {"feasibility": "TOO_SLOW_FOR_LIVE_ONLY_COLLECTION"},
    }


def _exit_upgrade(state: str = "UPGRADE_SUPPORTED_FOR_PAPER_ONLY") -> dict:
    return {
        "recommended_state": state,
        "reasons": ["candidate_exit_policy_dominates_baseline_on_core_metrics"],
        "baseline_exit_policy": "old_exit",
        "candidate_exit_policy": "new_exit",
        "delta_candidate_minus_baseline": {"total_r": 3.0},
        "candidate": {"total_r": 12.0},
        "baseline": {"total_r": 9.0},
    }


def _filter_upgrade(state: str = "UPGRADE_SUPPORTED_FOR_PAPER_ONLY") -> dict:
    return {
        "recommended_state": state,
        "reasons": ["candidate_filter_dominates_baseline_on_core_metrics"],
        "baseline_filter_policy": "old_filter",
        "candidate_filter_policy": "new_filter",
        "exit_policy": "new_exit",
        "delta_candidate_minus_baseline": {"total_r": 3.0},
        "candidate": {"total_r": 12.0},
        "baseline": {"total_r": 9.0},
    }


def _portfolio_mix(*, state: str = "PORTFOLIO_MIX_PAPER_WATCH", order_submission_allowed: bool = False) -> dict:
    return {
        "recommended_state": state,
        "reasons": ["combined_replay_supports_paper_watch"],
        "live_action": "KEEP_CLOSE_ONLY",
        "live_ready": False,
        "order_submission_allowed": order_submission_allowed,
        "combined_symbol_count": 12,
        "combined_symbols": ["BTCUSDT", "ADAUSDT"],
        "combined": {
            "summary": {
                "closed": 451,
                "total_r": 84.1429,
                "ev_r": 0.1866,
                "max_dd_r": 6.5096,
                "positive_year_fraction": 1.0,
            },
            "cost_stress": {
                "extra_0_05r_per_trade": {"total_r": 61.5929},
                "cost_x2_0": {"total_r": 28.592},
            },
        },
        "recommended_portfolio_replay_scenarios": [
            {"account_equity_usdt": 170.0, "max_concurrent_positions": 2, "return_pct": 82.08}
        ],
    }


def _runtime_guard(status: str = "PASS") -> dict:
    failures = []
    if status != "PASS":
        failures = [{"name": "micro_live_backtest_contract_alignment", "message": "aggregate_ev_r=-0.4279"}]
    return {
        "overall_status": status,
        "operational_status": status,
        "blocking_failures": failures,
    }


def _config_proposal(state: str = "CONFIG_PROPOSAL_READY_FOR_MANUAL_REVIEW") -> dict:
    return {
        "recommended_state": state,
        "live_action": "KEEP_CLOSE_ONLY",
        "live_ready": False,
        "order_submission_allowed": False,
        "proposal_blockers": [],
        "runtime_support_gaps": [] if state == "CONFIG_PROPOSAL_READY_FOR_MANUAL_REVIEW" else ["runtime_gap"],
        "symbol_count": 12,
        "exit_policy_name": "policy_a",
        "recommended_max_concurrent_positions": 2,
    }


def _config_dry_run(
    state: str = "DRY_RUN_PASS_NO_LIVE_AUTHORITY",
    *,
    order_submission_allowed: bool = False,
) -> dict:
    failures = []
    if state != "DRY_RUN_PASS_NO_LIVE_AUTHORITY":
        failures = [{"name": "portfolio_mix_performance", "message": "ev_r below threshold"}]
    return {
        "recommended_state": state,
        "live_action": "KEEP_CLOSE_ONLY",
        "live_ready": False,
        "order_submission_allowed": order_submission_allowed,
        "symbol_count": 12,
        "exit_policy_name": "structure_buffered_swing6_stop0.12_tpbuf0.08_pm_stop0.00r_advvol_any",
        "blocking_failures": failures,
        "warning_failures": [],
        "checks": [
            {
                "name": "proposal_no_live_authority",
                "status": "PASS",
                "severity": "blocking",
                "message": "mismatches=none",
            }
        ],
    }


def _safety(
    new_entry_allowed: bool = False,
    *,
    blocking_reason_code: str | None = "close_only_mode",
    config_close_only_active: bool = True,
) -> dict:
    return {
        "new_entry_allowed": new_entry_allowed,
        "blocking_reason_code": blocking_reason_code,
        "config_close_only_active": config_close_only_active,
        "close_only_active": False,
        "live_account_protection": {"open_position_count": 0, "open_order_count": 0},
    }


def test_governance_continues_paper_watch_when_safe(tmp_path: Path) -> None:
    contract = tmp_path / "contract.json"
    watch = tmp_path / "watch.json"
    replay = tmp_path / "replay.json"
    expansion = tmp_path / "expansion.json"
    expansion_shadow = tmp_path / "expansion_shadow.json"
    exit_upgrade = tmp_path / "exit_upgrade.json"
    filter_upgrade = tmp_path / "filter_upgrade.json"
    _write_json(contract, _contract())
    _write_json(watch, _watch())
    _write_json(replay, _replay())
    _write_json(expansion, _expansion())
    _write_json(expansion_shadow, _expansion_shadow_review())
    _write_json(exit_upgrade, _exit_upgrade())
    _write_json(filter_upgrade, _filter_upgrade())

    payload = governance.build_payload(
        contract,
        watch,
        replay,
        expansion,
        expansion_shadow,
        exit_upgrade,
        filter_upgrade,
        safety_payload=_safety(),
        generated_at=datetime(2026, 5, 18, tzinfo=UTC),
    )

    assert payload["recommended_state"] == "CONTINUE_PAPER_WATCH_AND_REPLAY"
    assert payload["live_action"] == "KEEP_CLOSE_ONLY"
    assert payload["operator_summary"]["order_submission_allowed"] is False
    assert payload["watch_assessment"]["base_signal_rejection_summary"]["rejected_count"] == 2
    assert payload["expansion_shadow_watch_assessment"]["recommended_state"] == "COLLECTING_SIGNALS"
    assert payload["expansion_shadow_watch_assessment"]["base_signal_rejection_summary"]["rejected_count"] == 1
    assert payload["exit_policy_upgrade_assessment"]["recommended_state"] == "UPGRADE_SUPPORTED_FOR_PAPER_ONLY"
    assert payload["filter_upgrade_assessment"]["recommended_state"] == "UPGRADE_SUPPORTED_FOR_PAPER_ONLY"


def test_governance_holds_if_new_entries_are_allowed(tmp_path: Path) -> None:
    contract = tmp_path / "contract.json"
    watch = tmp_path / "watch.json"
    replay = tmp_path / "replay.json"
    expansion = tmp_path / "expansion.json"
    _write_json(contract, _contract())
    _write_json(watch, _watch())
    _write_json(replay, _replay())
    _write_json(expansion, _expansion())

    payload = governance.build_payload(
        contract,
        watch,
        replay,
        expansion,
        safety_payload=_safety(new_entry_allowed=True),
        generated_at=datetime(2026, 5, 18, tzinfo=UTC),
    )

    assert payload["recommended_state"] == "GOVERNANCE_HOLD"
    assert "new_entries_unexpectedly_allowed" in payload["reasons"]


def test_governance_observes_active_runtime_when_supporting_surfaces_pass(tmp_path: Path) -> None:
    contract = tmp_path / "contract.json"
    watch = tmp_path / "watch.json"
    replay = tmp_path / "replay.json"
    expansion = tmp_path / "expansion.json"
    portfolio_mix = tmp_path / "portfolio_mix.json"
    config_proposal = tmp_path / "config_proposal.json"
    config_dry_run = tmp_path / "config_dry_run.json"
    runtime_guard = tmp_path / "runtime_guard.json"
    _write_json(contract, _contract())
    _write_json(watch, _watch())
    _write_json(replay, _replay())
    _write_json(expansion, _expansion())
    _write_json(portfolio_mix, _portfolio_mix())
    _write_json(config_proposal, _config_proposal())
    _write_json(config_dry_run, _config_dry_run())
    _write_json(runtime_guard, _runtime_guard())

    payload = governance.build_payload(
        contract,
        watch,
        replay,
        expansion,
        portfolio_mix_review_path=portfolio_mix,
        config_proposal_path=config_proposal,
        config_dry_run_path=config_dry_run,
        runtime_guard_path=runtime_guard,
        safety_payload=_safety(
            new_entry_allowed=True,
            blocking_reason_code=None,
            config_close_only_active=False,
        ),
        generated_at=datetime(2026, 5, 18, tzinfo=UTC),
    )

    assert payload["recommended_state"] == "RUNTIME_ACTIVE_OBSERVE"
    assert payload["reasons"] == ["runtime_active_with_passing_governance_surfaces"]
    assert payload["live_action"] == "OBSERVE_ACTIVE_RUNTIME"
    assert payload["live_ready"] is True
    assert payload["runtime_entries_allowed"] is True
    assert payload["governance_order_submission_allowed"] is False
    assert payload["operator_summary"]["order_submission_allowed"] is True
    assert payload["operator_summary"]["governance_order_submission_allowed"] is False
    assert "new_entries_unexpectedly_allowed" not in payload["safety_assessment"]["hard_blockers"]


def test_governance_holds_if_replay_is_not_supportive(tmp_path: Path) -> None:
    contract = tmp_path / "contract.json"
    watch = tmp_path / "watch.json"
    replay = tmp_path / "replay.json"
    expansion = tmp_path / "expansion.json"
    _write_json(contract, _contract())
    _write_json(watch, _watch())
    _write_json(replay, _replay("REPLAY_NOT_READY"))
    _write_json(expansion, _expansion())

    payload = governance.build_payload(
        contract,
        watch,
        replay,
        expansion,
        safety_payload=_safety(),
        generated_at=datetime(2026, 5, 18, tzinfo=UTC),
    )

    assert payload["recommended_state"] == "GOVERNANCE_HOLD"
    assert "replay_review_not_supportive" in payload["reasons"]


def test_governance_holds_if_expansion_is_ready_for_manual_review(tmp_path: Path) -> None:
    contract = tmp_path / "contract.json"
    watch = tmp_path / "watch.json"
    replay = tmp_path / "replay.json"
    expansion = tmp_path / "expansion.json"
    _write_json(contract, _contract())
    _write_json(watch, _watch())
    _write_json(replay, _replay())
    _write_json(expansion, _expansion("EXPANSION_REVIEW_READY"))

    payload = governance.build_payload(
        contract,
        watch,
        replay,
        expansion,
        safety_payload=_safety(),
        generated_at=datetime(2026, 5, 18, tzinfo=UTC),
    )

    assert payload["recommended_state"] == "GOVERNANCE_HOLD"
    assert "expansion_review_requires_manual_governance_before_live" in payload["reasons"]


def test_governance_holds_if_expansion_shadow_sample_is_ready(tmp_path: Path) -> None:
    contract = tmp_path / "contract.json"
    watch = tmp_path / "watch.json"
    replay = tmp_path / "replay.json"
    expansion = tmp_path / "expansion.json"
    expansion_shadow = tmp_path / "expansion_shadow.json"
    _write_json(contract, _contract())
    _write_json(watch, _watch())
    _write_json(replay, _replay())
    _write_json(expansion, _expansion())
    _write_json(expansion_shadow, _expansion_shadow_review("PAPER_SAMPLE_REVIEW_READY"))

    payload = governance.build_payload(
        contract,
        watch,
        replay,
        expansion,
        expansion_shadow,
        safety_payload=_safety(),
        generated_at=datetime(2026, 5, 18, tzinfo=UTC),
    )

    assert payload["recommended_state"] == "GOVERNANCE_HOLD"
    assert "expansion_shadow_sample_ready_requires_manual_review" in payload["reasons"]


def test_governance_holds_if_exit_policy_upgrade_review_is_not_supportive(tmp_path: Path) -> None:
    contract = tmp_path / "contract.json"
    watch = tmp_path / "watch.json"
    replay = tmp_path / "replay.json"
    expansion = tmp_path / "expansion.json"
    expansion_shadow = tmp_path / "expansion_shadow.json"
    exit_upgrade = tmp_path / "exit_upgrade.json"
    _write_json(contract, _contract())
    _write_json(watch, _watch())
    _write_json(replay, _replay())
    _write_json(expansion, _expansion())
    _write_json(expansion_shadow, _expansion_shadow_review())
    _write_json(exit_upgrade, _exit_upgrade("UPGRADE_REVIEW_HOLD"))

    payload = governance.build_payload(
        contract,
        watch,
        replay,
        expansion,
        expansion_shadow,
        exit_upgrade,
        safety_payload=_safety(),
        generated_at=datetime(2026, 5, 18, tzinfo=UTC),
    )

    assert payload["recommended_state"] == "GOVERNANCE_HOLD"
    assert "exit_policy_upgrade_review_not_supportive" in payload["reasons"]


def test_governance_holds_if_filter_upgrade_review_is_not_supportive(tmp_path: Path) -> None:
    contract = tmp_path / "contract.json"
    watch = tmp_path / "watch.json"
    replay = tmp_path / "replay.json"
    expansion = tmp_path / "expansion.json"
    expansion_shadow = tmp_path / "expansion_shadow.json"
    exit_upgrade = tmp_path / "exit_upgrade.json"
    filter_upgrade = tmp_path / "filter_upgrade.json"
    _write_json(contract, _contract())
    _write_json(watch, _watch())
    _write_json(replay, _replay())
    _write_json(expansion, _expansion())
    _write_json(expansion_shadow, _expansion_shadow_review())
    _write_json(exit_upgrade, _exit_upgrade())
    _write_json(filter_upgrade, _filter_upgrade("UPGRADE_REVIEW_HOLD"))

    payload = governance.build_payload(
        contract,
        watch,
        replay,
        expansion,
        expansion_shadow,
        exit_upgrade,
        filter_upgrade,
        safety_payload=_safety(),
        generated_at=datetime(2026, 5, 18, tzinfo=UTC),
    )

    assert payload["recommended_state"] == "GOVERNANCE_HOLD"
    assert "filter_upgrade_review_not_supportive" in payload["reasons"]


def test_governance_includes_portfolio_mix_and_runtime_guard_when_provided(tmp_path: Path) -> None:
    contract = tmp_path / "contract.json"
    watch = tmp_path / "watch.json"
    replay = tmp_path / "replay.json"
    expansion = tmp_path / "expansion.json"
    portfolio_mix = tmp_path / "portfolio_mix.json"
    config_dry_run = tmp_path / "config_dry_run.json"
    runtime_guard = tmp_path / "runtime_guard.json"
    _write_json(contract, _contract())
    _write_json(watch, _watch())
    _write_json(replay, _replay())
    _write_json(expansion, _expansion())
    _write_json(portfolio_mix, _portfolio_mix())
    _write_json(config_dry_run, _config_dry_run())
    _write_json(runtime_guard, _runtime_guard())

    payload = governance.build_payload(
        contract,
        watch,
        replay,
        expansion,
        portfolio_mix_review_path=portfolio_mix,
        config_dry_run_path=config_dry_run,
        runtime_guard_path=runtime_guard,
        safety_payload=_safety(),
        generated_at=datetime(2026, 5, 18, tzinfo=UTC),
    )

    assert payload["recommended_state"] == "CONTINUE_PAPER_WATCH_AND_REPLAY"
    assert payload["portfolio_mix_assessment"]["recommended_state"] == "PORTFOLIO_MIX_PAPER_WATCH"
    assert payload["portfolio_mix_assessment"]["order_submission_allowed"] is False
    assert payload["config_dry_run_assessment"]["recommended_state"] == "DRY_RUN_PASS_NO_LIVE_AUTHORITY"
    assert payload["config_dry_run_assessment"]["blocking_failure_count"] == 0
    assert payload["runtime_guard_assessment"]["overall_status"] == "PASS"


def test_governance_holds_when_runtime_guard_fails_even_if_portfolio_mix_is_good(tmp_path: Path) -> None:
    contract = tmp_path / "contract.json"
    watch = tmp_path / "watch.json"
    replay = tmp_path / "replay.json"
    expansion = tmp_path / "expansion.json"
    portfolio_mix = tmp_path / "portfolio_mix.json"
    runtime_guard = tmp_path / "runtime_guard.json"
    _write_json(contract, _contract())
    _write_json(watch, _watch())
    _write_json(replay, _replay())
    _write_json(expansion, _expansion())
    _write_json(portfolio_mix, _portfolio_mix())
    _write_json(runtime_guard, _runtime_guard("FAIL"))

    payload = governance.build_payload(
        contract,
        watch,
        replay,
        expansion,
        portfolio_mix_review_path=portfolio_mix,
        runtime_guard_path=runtime_guard,
        safety_payload=_safety(),
        generated_at=datetime(2026, 5, 18, tzinfo=UTC),
    )

    assert payload["recommended_state"] == "GOVERNANCE_HOLD"
    assert "runtime_guard_not_passing" in payload["reasons"]
    assert payload["runtime_guard_assessment"]["blocking_failure_count"] == 1


def test_governance_holds_if_portfolio_mix_allows_orders(tmp_path: Path) -> None:
    contract = tmp_path / "contract.json"
    watch = tmp_path / "watch.json"
    replay = tmp_path / "replay.json"
    expansion = tmp_path / "expansion.json"
    portfolio_mix = tmp_path / "portfolio_mix.json"
    runtime_guard = tmp_path / "runtime_guard.json"
    _write_json(contract, _contract())
    _write_json(watch, _watch())
    _write_json(replay, _replay())
    _write_json(expansion, _expansion())
    _write_json(portfolio_mix, _portfolio_mix(order_submission_allowed=True))
    _write_json(runtime_guard, _runtime_guard())

    payload = governance.build_payload(
        contract,
        watch,
        replay,
        expansion,
        portfolio_mix_review_path=portfolio_mix,
        runtime_guard_path=runtime_guard,
        safety_payload=_safety(),
        generated_at=datetime(2026, 5, 18, tzinfo=UTC),
    )

    assert payload["recommended_state"] == "GOVERNANCE_HOLD"
    assert "portfolio_mix_order_submission_allowed" in payload["reasons"]


def test_governance_holds_if_config_proposal_has_runtime_gaps(tmp_path: Path) -> None:
    contract = tmp_path / "contract.json"
    watch = tmp_path / "watch.json"
    replay = tmp_path / "replay.json"
    expansion = tmp_path / "expansion.json"
    portfolio_mix = tmp_path / "portfolio_mix.json"
    runtime_guard = tmp_path / "runtime_guard.json"
    config_proposal = tmp_path / "config_proposal.json"
    _write_json(contract, _contract())
    _write_json(watch, _watch())
    _write_json(replay, _replay())
    _write_json(expansion, _expansion())
    _write_json(portfolio_mix, _portfolio_mix())
    _write_json(runtime_guard, _runtime_guard())
    _write_json(config_proposal, _config_proposal("CONFIG_PROPOSAL_BLOCKED_FOR_RUNTIME_GAPS"))

    payload = governance.build_payload(
        contract,
        watch,
        replay,
        expansion,
        portfolio_mix_review_path=portfolio_mix,
        config_proposal_path=config_proposal,
        runtime_guard_path=runtime_guard,
        safety_payload=_safety(),
        generated_at=datetime(2026, 5, 18, tzinfo=UTC),
    )

    assert payload["recommended_state"] == "GOVERNANCE_HOLD"
    assert "live_config_proposal_not_ready" in payload["reasons"]
    assert payload["config_proposal_assessment"]["runtime_support_gaps"] == ["runtime_gap"]


def test_governance_holds_if_config_dry_run_fails(tmp_path: Path) -> None:
    contract = tmp_path / "contract.json"
    watch = tmp_path / "watch.json"
    replay = tmp_path / "replay.json"
    expansion = tmp_path / "expansion.json"
    portfolio_mix = tmp_path / "portfolio_mix.json"
    runtime_guard = tmp_path / "runtime_guard.json"
    config_dry_run = tmp_path / "config_dry_run.json"
    _write_json(contract, _contract())
    _write_json(watch, _watch())
    _write_json(replay, _replay())
    _write_json(expansion, _expansion())
    _write_json(portfolio_mix, _portfolio_mix())
    _write_json(runtime_guard, _runtime_guard())
    _write_json(config_dry_run, _config_dry_run("DRY_RUN_BLOCKED"))

    payload = governance.build_payload(
        contract,
        watch,
        replay,
        expansion,
        portfolio_mix_review_path=portfolio_mix,
        config_dry_run_path=config_dry_run,
        runtime_guard_path=runtime_guard,
        safety_payload=_safety(),
        generated_at=datetime(2026, 5, 18, tzinfo=UTC),
    )

    assert payload["recommended_state"] == "GOVERNANCE_HOLD"
    assert "config_dry_run_not_passing" in payload["reasons"]
    assert payload["config_dry_run_assessment"]["blocking_failure_count"] == 1


def test_governance_holds_if_config_dry_run_allows_orders(tmp_path: Path) -> None:
    contract = tmp_path / "contract.json"
    watch = tmp_path / "watch.json"
    replay = tmp_path / "replay.json"
    expansion = tmp_path / "expansion.json"
    portfolio_mix = tmp_path / "portfolio_mix.json"
    runtime_guard = tmp_path / "runtime_guard.json"
    config_dry_run = tmp_path / "config_dry_run.json"
    _write_json(contract, _contract())
    _write_json(watch, _watch())
    _write_json(replay, _replay())
    _write_json(expansion, _expansion())
    _write_json(portfolio_mix, _portfolio_mix())
    _write_json(runtime_guard, _runtime_guard())
    _write_json(config_dry_run, _config_dry_run(order_submission_allowed=True))

    payload = governance.build_payload(
        contract,
        watch,
        replay,
        expansion,
        portfolio_mix_review_path=portfolio_mix,
        config_dry_run_path=config_dry_run,
        runtime_guard_path=runtime_guard,
        safety_payload=_safety(),
        generated_at=datetime(2026, 5, 18, tzinfo=UTC),
    )

    assert payload["recommended_state"] == "GOVERNANCE_HOLD"
    assert "config_dry_run_has_live_authority" in payload["reasons"]
