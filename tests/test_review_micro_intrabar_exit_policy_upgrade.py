from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from scripts import review_micro_intrabar_exit_policy_upgrade as review


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _contract(subset_path: Path, exit_policy: str = "new_exit") -> dict:
    return {
        "candidate": {
            "source_path": str(subset_path),
            "source_policy_names": [exit_policy],
        },
        "paper_contract": {
            "policy_name": "volume12_body025_hour13_14_long",
            "exit_policy_name": exit_policy,
        },
    }


def _policy_row(policy: str, *, total_r: float, ev_r: float, max_dd_r: float, cost_x2: float) -> dict:
    return {
        "policy": policy,
        "summary": {
            "closed": 10,
            "total_r": total_r,
            "ev_r": ev_r,
            "win_rate": 0.5,
            "max_dd_r": max_dd_r,
            "profit_to_dd": total_r / max_dd_r,
            "positive_symbol_fraction": 0.75,
            "positive_year_fraction": 0.83,
        },
        "cost_stress": {
            "extra_0_05r_per_trade": {"total_r": total_r - 1.0},
            "cost_x2_0": {"total_r": cost_x2},
            "cost_x2_0_extra_0_03r_per_trade": {"total_r": cost_x2 - 0.3},
        },
    }


def _subset(*rows: dict) -> dict:
    return {
        "schema_version": "micro_main_intrabar_subset_report_v1",
        "results": [
            {
                "name": "volume12_body025_hour13_14_long",
                "by_policy": list(rows),
            }
        ],
    }


def test_upgrade_review_supports_candidate_that_dominates_baseline(tmp_path: Path) -> None:
    subset = tmp_path / "subset.json"
    contract = tmp_path / "contract.json"
    _write_json(
        subset,
        _subset(
            _policy_row("baseline", total_r=10.0, ev_r=0.1, max_dd_r=5.0, cost_x2=-1.0),
            _policy_row("new_exit", total_r=12.0, ev_r=0.12, max_dd_r=4.0, cost_x2=1.0),
        ),
    )
    _write_json(contract, _contract(subset))

    payload = review.build_payload(
        contract,
        baseline_exit_policy="baseline",
        generated_at=datetime(2026, 5, 18, tzinfo=UTC),
    )

    assert payload["recommended_state"] == "UPGRADE_SUPPORTED_FOR_PAPER_ONLY"
    assert payload["live_action"] == "KEEP_CLOSE_ONLY"
    assert payload["live_ready"] is False
    assert payload["delta_candidate_minus_baseline"]["total_r"] == 2.0
    assert payload["delta_candidate_minus_baseline"]["cost_x2_total_r"] == 2.0


def test_upgrade_review_holds_when_candidate_cost_x2_is_not_positive(tmp_path: Path) -> None:
    subset = tmp_path / "subset.json"
    contract = tmp_path / "contract.json"
    _write_json(
        subset,
        _subset(
            _policy_row("baseline", total_r=10.0, ev_r=0.1, max_dd_r=5.0, cost_x2=-1.0),
            _policy_row("new_exit", total_r=12.0, ev_r=0.12, max_dd_r=4.0, cost_x2=-0.1),
        ),
    )
    _write_json(contract, _contract(subset))

    payload = review.build_payload(
        contract,
        baseline_exit_policy="baseline",
        generated_at=datetime(2026, 5, 18, tzinfo=UTC),
    )

    assert payload["recommended_state"] == "UPGRADE_REVIEW_HOLD"
    assert "candidate_cost_x2_stress_not_positive" in payload["reasons"]


def test_upgrade_review_holds_when_policy_row_is_missing(tmp_path: Path) -> None:
    subset = tmp_path / "subset.json"
    contract = tmp_path / "contract.json"
    _write_json(subset, _subset(_policy_row("baseline", total_r=10.0, ev_r=0.1, max_dd_r=5.0, cost_x2=-1.0)))
    _write_json(contract, _contract(subset))

    payload = review.build_payload(
        contract,
        baseline_exit_policy="baseline",
        generated_at=datetime(2026, 5, 18, tzinfo=UTC),
    )

    assert payload["recommended_state"] == "UPGRADE_REVIEW_HOLD"
    assert "candidate_exit_policy_missing_from_subset_report" in payload["reasons"]
