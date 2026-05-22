from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from scripts import review_micro_intrabar_candidate_replay as replay


def _write_contract(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "paper_contract": {
                    "policy_name": "volume12_body025_hour13_14_long",
                    "exit_policy_name": "policy_a",
                    "symbols": ["BTCUSDT", "ETHUSDT"],
                    "filter_contract": {
                        "direction": "long",
                        "setup_hour_utc": [13, 14],
                        "min_volume_factor": 1.2,
                        "min_reclaim_body_atr": 0.25,
                    },
                }
            }
        ),
        encoding="utf-8",
    )


def _trade(
    symbol: str,
    entry_ts: str,
    r_value: float,
    *,
    volume: float = 1.3,
    body: float = 0.3,
    risk_atr: float = 0.6,
) -> dict:
    return {
        "symbol": symbol,
        "policy": "policy_a",
        "direction": "long",
        "entry_ts": entry_ts,
        "exit_ts": entry_ts,
        "entry_year": int(entry_ts[:4]),
        "r_value": r_value,
        "gross_r": r_value + 0.1,
        "cost_r": 0.1,
        "stop_distance_pct": 0.005,
        "hold_minutes": 10,
        "exit_reason": "target",
        "diagnostics": {
            "setup_hour_utc": 13,
            "volume_factor": volume,
            "reclaim_body_atr": body,
            "risk_atr": risk_atr,
        },
    }


def _write_intrabar_report(path: Path, trades: list[dict]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "micro_main_intrabar_research_v1",
                "generated_at": "2026-05-18T00:00:00+00:00",
                "results": [{"trades": trades}],
            }
        ),
        encoding="utf-8",
    )


def test_replay_review_filters_contract_and_summarizes_windows(tmp_path: Path) -> None:
    contract = tmp_path / "contract.json"
    report = tmp_path / "intrabar.json"
    _write_contract(contract)
    _write_intrabar_report(
        report,
        [
            _trade("BTCUSDT", "2026-05-18T13:00:00+00:00", 1.0),
            _trade("ETHUSDT", "2026-05-17T13:00:00+00:00", 1.0),
            _trade("BTCUSDT", "2025-05-18T13:00:00+00:00", -1.0),
            _trade("BTCUSDT", "2026-05-18T13:00:00+00:00", 1.0, volume=1.1),
        ],
    )

    payload = replay.build_payload(
        contract,
        intrabar_report_path=report,
        generated_at=datetime(2026, 5, 18, tzinfo=UTC),
    )

    assert payload["authority"] == "replay_review_only_no_order_submission"
    assert payload["live_action"] == "KEEP_CLOSE_ONLY"
    assert payload["matched_trade_count"] == 3
    assert payload["windows"][-1]["summary"]["total_r"] == 1.0


def test_replay_review_marks_last365_negative_as_not_ready(tmp_path: Path) -> None:
    contract = tmp_path / "contract.json"
    report = tmp_path / "intrabar.json"
    _write_contract(contract)
    _write_intrabar_report(
        report,
        [_trade("BTCUSDT", f"2026-05-{day:02d}T13:00:00+00:00", -1.0) for day in range(1, 11)]
        + [_trade("BTCUSDT", "2024-05-18T13:00:00+00:00", 20.0)],
    )

    payload = replay.build_payload(
        contract,
        intrabar_report_path=report,
        generated_at=datetime(2026, 5, 18, tzinfo=UTC),
    )

    assert payload["recommended_state"] == "REPLAY_NOT_READY"
    assert "last365_non_positive" in payload["reasons"]


def test_replay_review_applies_risk_atr_contract(tmp_path: Path) -> None:
    contract = tmp_path / "contract.json"
    report = tmp_path / "intrabar.json"
    _write_contract(contract)
    payload = json.loads(contract.read_text(encoding="utf-8"))
    payload["paper_contract"]["filter_contract"].pop("min_reclaim_body_atr")
    payload["paper_contract"]["filter_contract"]["min_risk_atr"] = 0.5
    contract.write_text(json.dumps(payload), encoding="utf-8")
    _write_intrabar_report(
        report,
        [
            _trade("BTCUSDT", "2026-05-18T13:00:00+00:00", 1.0, risk_atr=0.6),
            _trade("ETHUSDT", "2026-05-18T13:00:00+00:00", 1.0, risk_atr=0.4),
        ],
    )

    payload = replay.build_payload(
        contract,
        intrabar_report_path=report,
        generated_at=datetime(2026, 5, 18, tzinfo=UTC),
    )

    assert payload["matched_trade_count"] == 1
    assert payload["windows"][-1]["summary"]["total_r"] == 1.0


def test_replay_review_infers_intrabar_report_from_walkforward_source(tmp_path: Path) -> None:
    contract = tmp_path / "contract.json"
    walkforward = tmp_path / "walkforward.json"
    report = tmp_path / "intrabar.json"
    _write_contract(contract)
    contract_payload = json.loads(contract.read_text(encoding="utf-8"))
    contract_payload["candidate"] = {"source_path": str(walkforward)}
    contract.write_text(json.dumps(contract_payload), encoding="utf-8")
    walkforward.write_text(
        json.dumps(
            {
                "schema_version": "micro_intrabar_walkforward_symbol_filters_v1",
                "source": {"sources": [{"path": str(report)}]},
            }
        ),
        encoding="utf-8",
    )
    _write_intrabar_report(
        report,
        [_trade("BTCUSDT", "2026-05-18T13:00:00+00:00", 1.0)],
    )

    payload = replay.build_payload(
        contract,
        generated_at=datetime(2026, 5, 18, tzinfo=UTC),
    )

    assert payload["intrabar_report_path"] == str(report)
    assert payload["matched_trade_count"] == 1
