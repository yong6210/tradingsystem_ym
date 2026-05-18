from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from scripts import review_micro_intrabar_candidate_expansion as expansion


def _write_contract(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "paper_contract": {
                    "symbols": ["BTCUSDT", "ETHUSDT", "LINKUSDT", "DOGEUSDT"],
                    "exit_policy_name": "policy_a",
                    "filter_contract": {
                        "direction": "long",
                        "setup_hour_utc": [13],
                        "min_volume_factor": 1.2,
                        "min_reclaim_body_atr": 0.25,
                    },
                }
            }
        ),
        encoding="utf-8",
    )


def _trade(symbol: str, r_value: float, *, year: int = 2026) -> dict:
    return {
        "symbol": symbol,
        "policy": "policy_a",
        "direction": "long",
        "entry_ts": f"{year}-05-18T13:00:00+00:00",
        "exit_ts": f"{year}-05-18T13:10:00+00:00",
        "entry_year": year,
        "r_value": r_value,
        "gross_r": r_value + 0.01,
        "cost_r": 0.01,
        "stop_distance_pct": 0.005,
        "hold_minutes": 10,
        "exit_reason": "target",
        "diagnostics": {"setup_hour_utc": 13, "volume_factor": 1.3, "reclaim_body_atr": 0.3},
    }


def _write_report(path: Path, symbols: list[str], trades: list[dict], *, days: int = 365) -> None:
    path.write_text(
        json.dumps(
            {
                "scope": {
                    "symbols": symbols,
                    "days": days,
                    "entry_timing_model": "intrabar_1m_confirm_next_open",
                    "policy_names": ["policy_a"],
                },
                "results": [{"trades": trades}],
            }
        ),
        encoding="utf-8",
    )


def test_expansion_gate_rejects_broad_negative_report(tmp_path: Path) -> None:
    contract = tmp_path / "contract.json"
    report = tmp_path / "report.json"
    _write_contract(contract)
    symbols = [f"S{i}USDT" for i in range(8)]
    _write_report(report, symbols, [_trade(symbol, -1.0) for symbol in symbols])

    payload = expansion.build_payload(contract, [report], generated_at=datetime(2026, 5, 18, tzinfo=UTC))

    assert payload["recommended_state"] == "EXPANSION_NOT_READY"
    assert payload["report_reviews"][0]["expansion_gate"]["state"] == "EXPANSION_NOT_READY"
    assert "non_positive_base_result" in payload["report_reviews"][0]["expansion_gate"]["reasons"]
    assert payload["live_action"] == "KEEP_CLOSE_ONLY"


def test_expansion_can_create_shadow_watchlist_without_broad_pass(tmp_path: Path) -> None:
    contract = tmp_path / "contract.json"
    report = tmp_path / "report.json"
    _write_contract(contract)
    symbols = ["BTCUSDT", "ETHUSDT", "LINKUSDT", "DOGEUSDT", "SOLUSDT", "ADAUSDT", "LTCUSDT", "BNBUSDT"]
    trades = [
        _trade("SOLUSDT", 1.0),
        _trade("ADAUSDT", 1.0),
        _trade("LTCUSDT", 1.0),
        _trade("BNBUSDT", 1.0),
        _trade("BTCUSDT", -10.0),
    ]
    _write_report(report, symbols, trades)

    payload = expansion.build_payload(contract, [report], generated_at=datetime(2026, 5, 18, tzinfo=UTC))

    assert payload["recommended_state"] == "EXPANSION_SHADOW_WATCHLIST_ONLY"
    assert set(payload["shadow_watchlist_symbols"]) == {"ADAUSDT", "BNBUSDT", "LTCUSDT", "SOLUSDT"}
