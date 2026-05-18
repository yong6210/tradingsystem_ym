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


def _safety(new_entry_allowed: bool = False) -> dict:
    return {
        "new_entry_allowed": new_entry_allowed,
        "blocking_reason_code": "close_only_mode",
        "config_close_only_active": True,
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
