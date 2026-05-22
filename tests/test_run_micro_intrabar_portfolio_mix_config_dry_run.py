from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from scripts import run_micro_intrabar_portfolio_mix_config_dry_run as dry_run


class _FakeCandleRepo:
    def list_recent(self, *, symbol: str, timeframe: str, limit: int):
        return [object()] * int(limit)


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _portfolio_mix() -> dict:
    return {
        "recommended_state": "PORTFOLIO_MIX_PAPER_WATCH",
        "combined_symbols": ["BTCUSDT", "ADAUSDT", "ARBUSDT"],
        "combined": {
            "summary": {
                "closed": 120,
                "ev_r": 0.2,
                "positive_year_fraction": 1.0,
            },
            "cost_stress": {
                "cost_x2_0": {"total_r": 8.0},
                "extra_0_05r_per_trade": {"total_r": 12.0},
            },
        },
    }


def _config_proposal(*, order_submission_allowed: bool = False, symbols: list[str] | None = None) -> dict:
    symbols = symbols or ["BTCUSDT", "ADAUSDT", "ARBUSDT"]
    symbol_csv = ",".join(symbols)
    direction_contract = {"BTCUSDT": ["LONG"], "ADAUSDT": ["LONG"], "ARBUSDT": ["SHORT"]}
    direction_line = ",".join(f"{symbol}:{directions[0]}" for symbol, directions in direction_contract.items() if symbol in symbols)
    return {
        "authority": "config_proposal_only_no_file_edit_no_order_submission",
        "recommended_state": "CONFIG_PROPOSAL_READY_FOR_MANUAL_REVIEW",
        "proposal_blockers": [],
        "runtime_support_gaps": [],
        "live_action": "KEEP_CLOSE_ONLY",
        "live_ready": False,
        "order_submission_allowed": order_submission_allowed,
        "symbols": symbols,
        "direction_contract": {symbol: direction_contract[symbol] for symbol in symbols if symbol in direction_contract},
        "exit_policy_name": "structure_buffered_swing6_stop0.12_tpbuf0.08_pm_stop0.00r_advvol_any",
        "env_proposal": {
            "AUTO_TRADING_CLOSE_ONLY": "true",
            "AUTO_TRADING_MICRO_LIVE_ALLOWED_SYMBOLS": symbol_csv,
            "AUTO_TRADING_MICRO_LIVE_SYMBOL_PRIORITY": symbol_csv,
            "AUTO_TRADING_MICRO_LIVE_DIRECTION_CONTRACT": direction_line,
            "SESSION_IMPULSE_RETEST_ALLOWED_SYMBOLS": symbol_csv,
            "SESSION_IMPULSE_RETEST_EXIT_POLICY_NAME": "structure_buffered_swing6_stop0.12_tpbuf0.08_pm_stop0.00r_advvol_any",
            "SESSION_IMPULSE_RETEST_EXIT_STOP_MODE": "structure_floor",
            "SESSION_IMPULSE_RETEST_EXIT_TARGET_RR": "2.5",
            "SESSION_IMPULSE_RETEST_EXIT_TP1_FRACTION": "0.35",
            "SESSION_IMPULSE_RETEST_EXIT_TP2_FRACTION": "0.65",
            "SESSION_IMPULSE_RETEST_EXIT_MIN_STOP_PCT": "0.003",
            "SESSION_IMPULSE_RETEST_EXIT_MIN_RISK_ATR": "0.35",
            "SESSION_IMPULSE_RETEST_EXIT_ADAPTIVE_TARGETS_ENABLED": "true",
            "SESSION_IMPULSE_RETEST_EXIT_STRUCTURE_TARGETS_ENABLED": "true",
            "SESSION_IMPULSE_RETEST_EXIT_STRUCTURE_STOP_SWING_BARS": "6",
            "SESSION_IMPULSE_RETEST_EXIT_STRUCTURE_STOP_BUFFER_ATR": "0.12",
            "SESSION_IMPULSE_RETEST_EXIT_STRUCTURE_TARGET_BUFFER_ATR": "0.08",
            "SESSION_IMPULSE_RETEST_EXIT_STRUCTURE_TP1_MIN_RR": "0.8",
            "SESSION_IMPULSE_RETEST_EXIT_STRUCTURE_TP2_MIN_RR": "1.6",
            "SESSION_IMPULSE_RETEST_EXIT_STRUCTURE_TP_MAX_RR": "3.2",
            "SESSION_IMPULSE_RETEST_EXIT_STOP_AFTER_PARTIAL_RR": "0.0",
            "SESSION_IMPULSE_RETEST_EXIT_ADVERSE_VOLUME_ENABLED": "true",
            "SESSION_IMPULSE_RETEST_EXIT_ADVERSE_VOLUME_AFTER_PARTIAL_ONLY": "false",
            "SESSION_IMPULSE_RETEST_EXIT_ADVERSE_VOLUME_MIN_FACTOR": "3.0",
            "SESSION_IMPULSE_RETEST_EXIT_ADVERSE_VOLUME_MIN_BODY_R": "0.35",
            "SESSION_IMPULSE_RETEST_EXIT_ADVERSE_VOLUME_LOOKBACK_BARS": "20",
            "AUTO_TRADING_LIVE_BREAKEVEN_AFTER_PARTIAL_ENABLED": "true",
            "AUTO_TRADING_LIVE_BREAKEVEN_OFFSET_BPS": "0.0",
            "AUTO_TRADING_LIVE_BREAKEVEN_MIN_IMPROVEMENT_BPS": "0.0",
            "AUTO_TRADING_LIVE_ADVERSE_VOLUME_EXIT_ENABLED": "true",
            "AUTO_TRADING_LIVE_ADVERSE_VOLUME_EXIT_AFTER_PARTIAL_ONLY": "false",
        },
    }


def test_config_dry_run_passes_without_live_authority(tmp_path: Path) -> None:
    proposal_path = tmp_path / "proposal.json"
    portfolio_path = tmp_path / "portfolio.json"
    _write_json(proposal_path, _config_proposal())
    _write_json(portfolio_path, _portfolio_mix())

    payload = dry_run.build_payload(
        config_proposal_path=proposal_path,
        portfolio_mix_review_path=portfolio_path,
        generated_at=datetime(2026, 5, 20, tzinfo=UTC),
        candle_repo=_FakeCandleRepo(),
        include_leverage_check=False,
    )

    assert payload["recommended_state"] == "DRY_RUN_PASS_NO_LIVE_AUTHORITY"
    assert payload["order_submission_allowed"] is False
    assert payload["blocking_failures"] == []
    assert {check["name"]: check["status"] for check in payload["checks"]}["session_impulse_retest_exit_contract"] == "PASS"


def test_config_dry_run_blocks_live_authority_or_symbol_drift(tmp_path: Path) -> None:
    proposal_path = tmp_path / "proposal.json"
    portfolio_path = tmp_path / "portfolio.json"
    _write_json(proposal_path, _config_proposal(order_submission_allowed=True, symbols=["BTCUSDT", "ADAUSDT"]))
    _write_json(portfolio_path, _portfolio_mix())

    payload = dry_run.build_payload(
        config_proposal_path=proposal_path,
        portfolio_mix_review_path=portfolio_path,
        generated_at=datetime(2026, 5, 20, tzinfo=UTC),
        candle_repo=_FakeCandleRepo(),
        include_leverage_check=False,
    )

    assert payload["recommended_state"] == "DRY_RUN_BLOCKED"
    failure_names = {item["name"] for item in payload["blocking_failures"]}
    assert "proposal_no_live_authority" in failure_names
    assert "env_symbol_direction_contract" in failure_names
