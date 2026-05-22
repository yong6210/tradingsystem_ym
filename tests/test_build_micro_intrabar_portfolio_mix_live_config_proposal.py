from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from scripts import build_micro_intrabar_portfolio_mix_live_config_proposal as proposal


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _contract(*, direction: str, symbols: list[str]) -> dict:
    return {
        "authority": "paper_only_no_live_authority_change",
        "live_action": "KEEP_CLOSE_ONLY",
        "live_ready": False,
        "paper_contract": {
            "exit_policy_name": "structure_buffered_swing6_stop0.12_tpbuf0.08_pm_stop0.00r_advvol_any",
            "symbols": symbols,
            "filter_contract": {"direction": direction},
        },
    }


def _portfolio_mix() -> dict:
    return {
        "recommended_state": "PORTFOLIO_MIX_PAPER_WATCH",
        "live_action": "KEEP_CLOSE_ONLY",
        "live_ready": False,
        "order_submission_allowed": False,
        "combined_symbols": ["BTCUSDT", "ADAUSDT", "ARBUSDT"],
        "operator_summary": {"recommended_max_concurrent_positions": 2},
    }


def test_live_config_proposal_keeps_close_only_and_symbol_directions(tmp_path: Path) -> None:
    mix = tmp_path / "mix.json"
    long_contract = tmp_path / "long.json"
    short_contract = tmp_path / "short.json"
    _write_json(mix, _portfolio_mix())
    _write_json(long_contract, _contract(direction="long", symbols=["BTCUSDT", "ADAUSDT"]))
    _write_json(short_contract, _contract(direction="short", symbols=["ARBUSDT"]))

    payload = proposal.build_payload(
        portfolio_mix_review_path=mix,
        contract_paths=[long_contract, short_contract],
        generated_at=datetime(2026, 5, 20, tzinfo=UTC),
    )

    assert payload["authority"] == "config_proposal_only_no_file_edit_no_order_submission"
    assert payload["live_action"] == "KEEP_CLOSE_ONLY"
    assert payload["order_submission_allowed"] is False
    assert payload["direction_contract"] == {
        "BTCUSDT": ["LONG"],
        "ADAUSDT": ["LONG"],
        "ARBUSDT": ["SHORT"],
    }
    assert payload["env_proposal"]["AUTO_TRADING_CLOSE_ONLY"] == "true"
    assert payload["env_proposal"]["AUTO_TRADING_MICRO_LIVE_MAX_CONCURRENT_POSITIONS"] == "2"
    assert int(payload["env_proposal"]["SESSION_IMPULSE_RETEST_CORE_LIVE_SLOTS"]) >= len(
        payload["env_proposal"]["SESSION_IMPULSE_RETEST_ALLOWED_SYMBOLS"].split(",")
    )
    assert payload["required_core_live_slots"] == int(payload["env_proposal"]["SESSION_IMPULSE_RETEST_CORE_LIVE_SLOTS"])
    assert payload["env_proposal"]["SESSION_IMPULSE_RETEST_EXIT_STOP_MODE"] == "structure_floor"
    assert payload["env_proposal"]["AUTO_TRADING_LIVE_BREAKEVEN_AFTER_PARTIAL_ENABLED"] == "true"
    assert payload["env_proposal"]["AUTO_TRADING_LIVE_BREAKEVEN_OFFSET_BPS"] == "0.0"
    assert payload["env_proposal"]["SESSION_IMPULSE_RETEST_EXIT_ADVERSE_VOLUME_ENABLED"] == "true"
    assert payload["env_proposal"]["AUTO_TRADING_LIVE_ADVERSE_VOLUME_EXIT_ENABLED"] == "true"
    assert "adverse_volume_exit_is_not_wired_as_live_position_management" not in payload["runtime_support_gaps"]
    assert "live_stop_after_partial_must_be_verified_against_candidate_policy" not in payload["runtime_support_gaps"]
    assert payload["runtime_support_gaps"] == []
    assert payload["recommended_state"] == "CONFIG_PROPOSAL_READY_FOR_MANUAL_REVIEW"


def test_live_config_proposal_blocks_direction_conflict(tmp_path: Path) -> None:
    mix = tmp_path / "mix.json"
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    _write_json(mix, {**_portfolio_mix(), "combined_symbols": ["BTCUSDT"]})
    _write_json(first, _contract(direction="long", symbols=["BTCUSDT"]))
    _write_json(second, _contract(direction="short", symbols=["BTCUSDT"]))

    payload = proposal.build_payload(
        portfolio_mix_review_path=mix,
        contract_paths=[first, second],
        generated_at=datetime(2026, 5, 20, tzinfo=UTC),
    )

    assert any(str(item).startswith("direction_conflict:BTCUSDT") for item in payload["proposal_blockers"])


def test_live_config_proposal_allows_intentional_contract_subset(tmp_path: Path) -> None:
    mix = tmp_path / "mix.json"
    long_contract = tmp_path / "long.json"
    _write_json(mix, _portfolio_mix())
    _write_json(long_contract, _contract(direction="long", symbols=["BTCUSDT", "ADAUSDT"]))

    payload = proposal.build_payload(
        portfolio_mix_review_path=mix,
        contract_paths=[long_contract],
        allow_contract_subset=True,
        generated_at=datetime(2026, 5, 20, tzinfo=UTC),
    )

    assert payload["recommended_state"] == "CONFIG_PROPOSAL_READY_FOR_MANUAL_REVIEW"
    assert payload["allow_contract_subset"] is True
    assert payload["proposal_blockers"] == []
    assert payload["symbols"] == ["BTCUSDT", "ADAUSDT"]
    assert payload["direction_contract"] == {"BTCUSDT": ["LONG"], "ADAUSDT": ["LONG"]}
    assert payload["env_proposal"]["AUTO_TRADING_MICRO_LIVE_DIRECTION_CONTRACT"] == "BTCUSDT:LONG,ADAUSDT:LONG"
