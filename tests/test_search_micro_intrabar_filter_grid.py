from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from scripts import search_micro_intrabar_filter_grid as grid


def _trade(
    *,
    symbol: str,
    direction: str,
    hour: int,
    r_value: float,
    year: int,
    policy: str = "p",
) -> dict:
    return {
        "policy": policy,
        "symbol": symbol,
        "direction": direction,
        "entry_ts": f"{year}-05-18T{hour:02d}:00:00+00:00",
        "exit_ts": f"{year}-05-18T{hour:02d}:05:00+00:00",
        "entry_year": year,
        "r_value": r_value,
        "gross_r": r_value + 0.05,
        "cost_r": 0.05,
        "stop_distance_pct": 0.006,
        "hold_minutes": 5,
        "exit_reason": "target" if r_value > 0 else "stop",
        "diagnostics": {
            "setup_hour_utc": hour,
            "volume_factor": 1.3,
            "reclaim_body_atr": 0.3,
            "risk_atr": 0.8,
            "retest_wait_minutes": 1,
            "entry_distance_atr": 0.2,
        },
    }


def test_filter_grid_finds_faster_positive_candidate(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "schema_version": "micro_main_intrabar_research_v1",
                "generated_at": "2026-05-18T00:00:00+00:00",
                "scope": {
                    "days": 30,
                    "symbols": ["BTCUSDT", "ETHUSDT", "LINKUSDT", "DOGEUSDT"],
                    "entry_timing_model": "intrabar_1m_confirm_next_open",
                    "policy_names": ["p"],
                },
                "results": [
                    {
                        "trades": [
                            _trade(symbol="BTCUSDT", direction="long", hour=13, r_value=1.0, year=2025),
                            _trade(symbol="LINKUSDT", direction="long", hour=13, r_value=0.8, year=2025),
                            _trade(symbol="DOGEUSDT", direction="long", hour=14, r_value=0.7, year=2026),
                            _trade(symbol="ETHUSDT", direction="long", hour=14, r_value=0.6, year=2026),
                            _trade(symbol="BTCUSDT", direction="short", hour=8, r_value=-1.0, year=2025),
                            _trade(symbol="ETHUSDT", direction="short", hour=9, r_value=-1.0, year=2026),
                        ]
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = grid.build_payload(
        [report],
        policy_names={"p"},
        min_trades=2,
        max_results=5,
        generated_at=datetime(2026, 5, 18, tzinfo=UTC),
    )

    assert payload["authority"] == "research_only_no_live_authority_change"
    assert payload["candidate_count"] > 0
    assert payload["candidates"][0]["decision"] == "FASTER_PAPER_CANDIDATE"
    assert payload["candidates"][0]["summary"]["total_r"] > 0
    assert payload["candidates"][0]["estimated_days_to_30_signals"] <= 200


def test_decision_rejects_fee_stress_consistency_break() -> None:
    decision, reasons = grid._decision(
        {
            "closed": 120,
            "total_r": 10.0,
            "ev_r": 0.08,
            "profit_to_dd": 1.2,
            "positive_symbol_fraction": 0.75,
            "positive_year_fraction": 1.0,
        },
        {
            "extra_0_05r_per_trade": {
                "total_r": 2.0,
                "positive_symbol_fraction": 0.75,
                "positive_year_fraction": 0.5,
            },
            "cost_x2_0": {"total_r": 1.0},
        },
        days=365,
    )

    assert decision == "REJECT"
    assert "extra_0_05r_weak_year_consistency" in reasons
