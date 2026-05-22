from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts import review_micro_intrabar_candidate_portfolio_mix as mix


def _write_contract(path: Path, *, policy_name: str, symbol: str, direction: str, hour: int) -> None:
    path.write_text(
        json.dumps(
            {
                "authority": "paper_only_no_live_authority_change",
                "live_action": "KEEP_CLOSE_ONLY",
                "live_ready": False,
                "paper_contract": {
                    "policy_name": policy_name,
                    "exit_policy_name": "policy_a",
                    "symbols": [symbol],
                    "live_risk_r": 0.0,
                    "filter_contract": {
                        "direction": direction,
                        "setup_hour_utc": [hour],
                        "min_volume_factor": 0.0,
                        "min_reclaim_body_atr": 0.0,
                        "min_risk_atr": 0.0,
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def _trade(
    *,
    symbol: str,
    direction: str,
    entry_ts: datetime,
    r_value: float,
    hour: int,
    entry_price: float = 100.0,
    stop_price: float = 99.0,
) -> dict:
    return {
        "symbol": symbol,
        "policy": "policy_a",
        "direction": direction,
        "entry_ts": entry_ts.isoformat(),
        "exit_ts": (entry_ts + timedelta(minutes=10)).isoformat(),
        "entry_year": entry_ts.year,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "r_value": r_value,
        "gross_r": r_value + 0.1,
        "cost_r": 0.1,
        "stop_distance_pct": abs(entry_price - stop_price) / entry_price,
        "hold_minutes": 10,
        "exit_reason": "target",
        "diagnostics": {
            "setup_hour_utc": hour,
            "volume_factor": 1.0,
            "reclaim_body_atr": 0.5,
            "risk_atr": 0.5,
        },
    }


def _write_intrabar_report(path: Path, rows: list[dict]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "micro_main_intrabar_research_v1",
                "generated_at": "2026-05-18T00:00:00+00:00",
                "results": [{"trades": rows}],
            }
        ),
        encoding="utf-8",
    )


def test_portfolio_mix_combines_contracts_without_live_authority(tmp_path: Path) -> None:
    long_contract = tmp_path / "long.json"
    short_contract = tmp_path / "short.json"
    report = tmp_path / "intrabar.json"
    _write_contract(long_contract, policy_name="long_h14", symbol="BTCUSDT", direction="long", hour=14)
    _write_contract(short_contract, policy_name="short_h07", symbol="ETHUSDT", direction="short", hour=7)
    _write_intrabar_report(
        report,
        [
            _trade(
                symbol="BTCUSDT",
                direction="long",
                entry_ts=datetime(2026, 5, 18, 14, 0, tzinfo=UTC),
                r_value=1.0,
                hour=14,
                stop_price=99.0,
            ),
            _trade(
                symbol="ETHUSDT",
                direction="short",
                entry_ts=datetime(2026, 5, 18, 7, 0, tzinfo=UTC),
                r_value=2.0,
                hour=7,
                stop_price=101.0,
            ),
        ],
    )

    payload = mix.build_payload(
        [long_contract, short_contract],
        intrabar_report_path=report,
        days=365,
        account_equities=[100.0],
        max_concurrent_positions_values=[2],
        symbol_rules={
            "BTCUSDT": {"quantity_step": 0.001, "min_quantity": 0.001},
            "ETHUSDT": {"quantity_step": 0.001, "min_quantity": 0.001},
        },
        generated_at=datetime(2026, 5, 18, tzinfo=UTC),
    )

    assert payload["authority"] == "portfolio_mix_review_only_no_order_submission"
    assert payload["live_action"] == "KEEP_CLOSE_ONLY"
    assert payload["live_ready"] is False
    assert payload["order_submission_allowed"] is False
    assert payload["recommended_state"] == "PORTFOLIO_MIX_PAPER_WATCH"
    assert payload["combined"]["summary"]["closed"] == 2
    assert payload["combined"]["summary"]["total_r"] == 3.0
    scenario = payload["portfolio_replay"]["scenarios"][0]
    assert scenario["yearly_totals"]["accepted_trades"] == 2
    assert scenario["yearly_totals"]["rejected_trades_min_qty"] == 0
    assert payload["recommended_portfolio_replay_scenarios"][0]["max_concurrent_positions"] == 2
    assert payload["operator_summary"]["recommended_max_concurrent_positions"] == 2


def test_portfolio_mix_dedupes_overlapping_contracts(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    report = tmp_path / "intrabar.json"
    _write_contract(first, policy_name="long_h14_a", symbol="BTCUSDT", direction="long", hour=14)
    _write_contract(second, policy_name="long_h14_b", symbol="BTCUSDT", direction="long", hour=14)
    _write_intrabar_report(
        report,
        [
            _trade(
                symbol="BTCUSDT",
                direction="long",
                entry_ts=datetime(2026, 5, 18, 14, 0, tzinfo=UTC),
                r_value=1.0,
                hour=14,
            )
        ],
    )

    payload = mix.build_payload(
        [first, second],
        intrabar_report_path=report,
        days=365,
        account_equities=[100.0],
        max_concurrent_positions_values=[2],
        symbol_rules={"BTCUSDT": {"quantity_step": 0.001, "min_quantity": 0.001}},
        generated_at=datetime(2026, 5, 18, tzinfo=UTC),
    )

    assert payload["combined"]["summary"]["closed"] == 1
    assert payload["duplicate_trade_count"] == 1
