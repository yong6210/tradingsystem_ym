from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts import run_micro_intrabar_paper_candidate_contract as contract


def _write_ladder(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "micro_research_candidate_ladder_v1",
                "observations": [
                    {
                        "decision": "REJECT",
                        "family": "session_impulse_retest_intrabar_subset",
                        "policy_name": "bad",
                        "symbols": ["BTCUSDT"],
                    },
                    {
                        "decision": "PAPER_CANDIDATE",
                        "family": "session_impulse_retest_intrabar_subset",
                        "policy_name": "volume12_hour13_14_long",
                        "symbols": ["BTCUSDT", "ETHUSDT", "LINKUSDT", "DOGEUSDT"],
                        "symbol_count": 4,
                        "entry_timing_model": "intrabar_1m_confirm_next_open",
                        "closed": 155,
                        "total_r": 14.5728,
                        "ev_r": 0.094,
                        "profit_to_dd": 1.7362,
                        "positive_year_fraction": 0.8333,
                        "positive_symbol_fraction": 0.75,
                        "cost_stress": {
                            "extra_0_05r_per_trade": {"total_r": 6.8},
                            "cost_x2_0": {"total_r": -4.6}
                        }
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def test_build_payload_keeps_candidate_paper_only(tmp_path: Path) -> None:
    ladder = tmp_path / "ladder.json"
    _write_ladder(ladder)

    payload = contract.build_payload(ladder, generated_at=datetime(2026, 5, 18, tzinfo=UTC))

    assert payload["authority"] == "paper_only_no_live_authority_change"
    assert payload["live_action"] == "KEEP_CLOSE_ONLY"
    assert payload["live_ready"] is False
    assert payload["paper_contract"]["policy_name"] == "volume12_hour13_14_long"
    assert payload["paper_contract"]["live_risk_r"] == 0.0
    assert payload["promotion_gates"]["full_live_review_requires_symbol_count_at_least"] == 8
    assert "turns negative" in payload["risk_notes"][-1]


def test_select_candidate_prefers_fee_stress_robust_row() -> None:
    payload = {
        "observations": [
            {
                "decision": "PAPER_CANDIDATE",
                "family": "session_impulse_retest_intrabar_subset",
                "policy_name": "higher_total",
                "total_r": 15.0,
                "ev_r": 0.09,
                "closed": 155,
                "cost_stress": {"extra_0_05r_per_trade": {"total_r": 6.0}},
            },
            {
                "decision": "PAPER_CANDIDATE",
                "family": "session_impulse_retest_intrabar_subset",
                "policy_name": "better_stress",
                "total_r": 14.0,
                "ev_r": 0.10,
                "closed": 136,
                "cost_stress": {"extra_0_05r_per_trade": {"total_r": 7.0}},
            },
        ]
    }

    row = contract._select_candidate(payload)

    assert row["policy_name"] == "better_stress"


def test_select_candidate_can_pin_name(tmp_path: Path) -> None:
    ladder = tmp_path / "ladder.json"
    _write_ladder(ladder)
    payload = json.loads(ladder.read_text(encoding="utf-8"))

    row = contract._select_candidate(payload, candidate_name="volume12_hour13_14_long")

    assert row["policy_name"] == "volume12_hour13_14_long"


def test_contract_describes_risk_atr_filter(tmp_path: Path) -> None:
    ladder = tmp_path / "ladder.json"
    ladder.write_text(
        json.dumps(
            {
                "schema_version": "micro_research_candidate_ladder_v1",
                "observations": [
                    {
                        "decision": "PAPER_CANDIDATE",
                        "family": "session_impulse_retest_intrabar_subset",
                        "policy_name": "volume12_risk05_hour13_14_long",
                        "symbols": ["BTCUSDT", "ETHUSDT", "LINKUSDT", "DOGEUSDT"],
                        "symbol_count": 4,
                        "entry_timing_model": "intrabar_1m_confirm_next_open",
                        "closed": 130,
                        "total_r": 21.4997,
                        "ev_r": 0.1654,
                        "profit_to_dd": 3.6778,
                        "positive_year_fraction": 0.8333,
                        "positive_symbol_fraction": 1.0,
                        "cost_stress": {
                            "extra_0_05r_per_trade": {"total_r": 14.9997},
                            "cost_x2_0": {"total_r": 5.6502},
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = contract.build_payload(ladder, generated_at=datetime(2026, 5, 18, tzinfo=UTC))

    assert payload["paper_contract"]["filter_contract"]["min_risk_atr"] == 0.5
    assert payload["paper_contract"]["filter_contract"]["setup_hour_utc"] == [13, 14]


def test_report_stamp_includes_microseconds_to_avoid_same_second_collision() -> None:
    first = datetime(2026, 5, 18, 0, 0, 0, 1, tzinfo=UTC)
    second = first + timedelta(microseconds=1)

    assert contract._report_stamp(first) != contract._report_stamp(second)
