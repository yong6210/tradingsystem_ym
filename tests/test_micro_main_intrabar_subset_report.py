from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts import run_micro_main_intrabar_subset_report as subset_report


def test_subset_report_filters_volume_hour_and_long(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18T00:00:00+00:00",
                "scope": {"days": 90},
                "results": [
                    {
                        "trades": [
                            {
                                "policy": "p",
                                "symbol": "BTCUSDT",
                                "direction": "long",
                                "entry_ts": "2026-05-18T13:00:00+00:00",
                                "exit_ts": "2026-05-18T13:01:00+00:00",
                                "entry_year": 2026,
                                "r_value": 1.0,
                                "gross_r": 1.1,
                                "cost_r": 0.1,
                                "stop_distance_pct": 0.01,
                                "hold_minutes": 1,
                                "exit_reason": "target",
                                "diagnostics": {
                                    "volume_factor": 1.3,
                                    "setup_hour_utc": 13,
                                    "reclaim_body_atr": 0.3,
                                },
                            },
                            {
                                "policy": "p",
                                "symbol": "ETHUSDT",
                                "direction": "short",
                                "entry_ts": "2026-05-18T13:00:00+00:00",
                                "exit_ts": "2026-05-18T13:01:00+00:00",
                                "entry_year": 2026,
                                "r_value": -1.0,
                                "gross_r": -0.9,
                                "cost_r": 0.1,
                                "stop_distance_pct": 0.01,
                                "hold_minutes": 1,
                                "exit_reason": "stop",
                                "diagnostics": {
                                    "volume_factor": 1.3,
                                    "setup_hour_utc": 13,
                                    "reclaim_body_atr": 0.3,
                                },
                            },
                        ]
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = subset_report.build_payload(
        report,
        {"candidate": subset_report._built_in_filters()["volume12_body025_hour13_14_long"]},
        generated_at=datetime(2026, 5, 18, tzinfo=UTC),
    )

    assert payload["authority"] == "compare_only_no_live_authority_change"
    assert payload["baseline"]["closed"] == 2
    assert payload["results"][0]["summary"]["closed"] == 1
    assert payload["results"][0]["summary"]["total_r"] == 1.0
    assert payload["results"][0]["source_policy_count"] == 1
    assert payload["results"][0]["by_policy"][0]["policy"] == "p"
    assert payload["results"][0]["by_symbol_total_r"] == {"BTCUSDT": 1.0}


def test_subset_report_supports_risk_atr_candidate_filter(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    common = {
        "policy": "p",
        "symbol": "BTCUSDT",
        "direction": "long",
        "entry_ts": "2026-05-18T13:00:00+00:00",
        "exit_ts": "2026-05-18T13:01:00+00:00",
        "entry_year": 2026,
        "gross_r": 1.1,
        "cost_r": 0.1,
        "stop_distance_pct": 0.01,
        "hold_minutes": 1,
        "exit_reason": "target",
    }
    report.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18T00:00:00+00:00",
                "scope": {"days": 90},
                "results": [
                    {
                        "trades": [
                            {
                                **common,
                                "r_value": 1.0,
                                "diagnostics": {
                                    "volume_factor": 1.3,
                                    "setup_hour_utc": 14,
                                    "risk_atr": 0.55,
                                },
                            },
                            {
                                **common,
                                "r_value": -1.0,
                                "diagnostics": {
                                    "volume_factor": 1.3,
                                    "setup_hour_utc": 14,
                                    "risk_atr": 0.45,
                                },
                            },
                        ]
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = subset_report.build_payload(
        report,
        {"candidate": subset_report._built_in_filters()["volume12_risk05_hour13_14_long"]},
        generated_at=datetime(2026, 5, 18, tzinfo=UTC),
    )

    assert payload["results"][0]["summary"]["closed"] == 1
    assert payload["results"][0]["summary"]["total_r"] == 1.0


def test_report_stamp_includes_microseconds_to_avoid_same_second_collision() -> None:
    first = datetime(2026, 5, 18, 0, 0, 0, 1, tzinfo=UTC)
    second = first + timedelta(microseconds=1)

    assert subset_report._report_stamp(first) != subset_report._report_stamp(second)


def test_subset_report_keeps_policy_breakdowns_when_multiple_policies_pass(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    common = {
        "symbol": "BTCUSDT",
        "direction": "long",
        "entry_ts": "2026-05-18T13:00:00+00:00",
        "exit_ts": "2026-05-18T13:01:00+00:00",
        "entry_year": 2026,
        "gross_r": 1.0,
        "cost_r": 0.1,
        "stop_distance_pct": 0.01,
        "hold_minutes": 1,
        "exit_reason": "target",
        "diagnostics": {
            "volume_factor": 1.3,
            "setup_hour_utc": 13,
            "reclaim_body_atr": 0.3,
        },
    }
    report.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18T00:00:00+00:00",
                "scope": {"days": 90},
                "results": [
                    {"trades": [{**common, "policy": "p1", "r_value": 1.0}]},
                    {"trades": [{**common, "policy": "p2", "r_value": 2.0}]},
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = subset_report.build_payload(
        report,
        {"candidate": subset_report._built_in_filters()["volume12_body025_hour13_14_long"]},
        generated_at=datetime(2026, 5, 18, tzinfo=UTC),
    )

    result = payload["results"][0]
    assert result["summary"]["closed"] == 2
    assert result["source_policy_count"] == 2
    assert [item["policy"] for item in result["by_policy"]] == ["p2", "p1"]
    assert result["by_policy"][0]["summary"]["total_r"] == 2.0
