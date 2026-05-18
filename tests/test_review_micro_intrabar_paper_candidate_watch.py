from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from scripts import review_micro_intrabar_paper_candidate_watch as review


def _write_contract(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "promotion_gates": {
                    "minimum_closed_paper_trades": 2,
                    "minimum_observation_days": 1,
                },
                "paper_contract": {
                    "policy_name": "volume12_body025_hour13_14_long",
                    "symbols": ["BTCUSDT", "ETHUSDT"],
                },
                "candidate": {
                    "closed": 200,
                    "days": 100,
                },
            }
        ),
        encoding="utf-8",
    )


def _write_watch_report(
    path: Path,
    *,
    generated_at: str,
    candidates: list[dict],
    base_signals: list[dict] | None = None,
) -> None:
    base_signals = list(base_signals or [])
    path.write_text(
        json.dumps(
            {
                "schema_version": "micro_intrabar_paper_candidate_watch_v1",
                "generated_at": generated_at,
                "status": "WATCHING",
                "summary": {
                    "base_signals": {"count": len(base_signals)},
                    "paper_candidates": {"count": len(candidates)},
                    "fresh_paper_candidates": {"count": 0},
                },
                "latest_candidates": candidates,
                "latest_base_signals": base_signals,
            }
        ),
        encoding="utf-8",
    )


def _candidate(symbol: str, entry_ts: str) -> dict:
    return {
        "symbol": symbol,
        "direction": "long",
        "entry_ts": entry_ts,
        "diagnostics": {"setup_hour_utc": 13},
    }


def _base_signal(symbol: str, entry_ts: str, reasons: list[str]) -> dict:
    return {
        "symbol": symbol,
        "direction": "short" if "direction_mismatch" in reasons else "long",
        "entry_ts": entry_ts,
        "filter_pass": not reasons,
        "filter_reasons": reasons,
        "diagnostics": {"setup_hour_utc": 7 if "setup_hour_not_allowed" in reasons else 13},
    }


def test_dedupes_overlapping_watch_reports(tmp_path: Path) -> None:
    contract = tmp_path / "contract.json"
    _write_contract(contract)
    first = tmp_path / "watch_1.json"
    second = tmp_path / "watch_2.json"
    duplicate = _candidate("BTCUSDT", "2026-05-18T13:01:00+00:00")
    _write_watch_report(
        first,
        generated_at="2026-05-18T14:00:00+00:00",
        candidates=[duplicate, _candidate("ETHUSDT", "2026-05-17T13:01:00+00:00")],
    )
    _write_watch_report(
        second,
        generated_at="2026-05-18T15:00:00+00:00",
        candidates=[duplicate],
    )

    payload = review.build_payload(
        contract,
        [first, second],
        review_label="expansion_shadow_watchlist",
        generated_at=datetime(2026, 5, 18, tzinfo=UTC),
    )

    assert payload["review_label"] == "expansion_shadow_watchlist"
    assert payload["unique_candidate_summary"]["count"] == 2
    assert payload["unique_candidate_summary"]["by_symbol"] == {"BTCUSDT": 1, "ETHUSDT": 1}
    assert payload["recommended_state"] == "PAPER_SAMPLE_REVIEW_READY"
    assert payload["live_action"] == "KEEP_CLOSE_ONLY"
    assert payload["live_ready"] is False
    assert payload["collection_estimate"]["feasibility"] == "PRACTICAL_LIVE_COLLECTION"


def test_review_blocks_when_no_unique_candidates(tmp_path: Path) -> None:
    contract = tmp_path / "contract.json"
    _write_contract(contract)
    report = tmp_path / "watch.json"
    _write_watch_report(report, generated_at="2026-05-18T14:00:00+00:00", candidates=[])

    payload = review.build_payload(contract, [report], generated_at=datetime(2026, 5, 18, tzinfo=UTC))

    assert payload["recommended_state"] == "COLLECTING_SIGNALS"
    assert "no_unique_candidate_signals_yet" in payload["blockers"]


def test_review_flags_live_only_collection_when_historical_rate_is_too_slow(tmp_path: Path) -> None:
    contract = tmp_path / "contract.json"
    contract.write_text(
        json.dumps(
            {
                "promotion_gates": {
                    "minimum_closed_paper_trades": 30,
                    "minimum_observation_days": 30,
                },
                "paper_contract": {
                    "policy_name": "volume12_body025_hour13_14_long",
                    "symbols": ["BTCUSDT", "ETHUSDT"],
                },
                "candidate": {
                    "closed": 136,
                    "days": 1825,
                },
            }
        ),
        encoding="utf-8",
    )
    report = tmp_path / "watch.json"
    _write_watch_report(report, generated_at="2026-05-18T14:00:00+00:00", candidates=[])

    payload = review.build_payload(contract, [report], generated_at=datetime(2026, 5, 18, tzinfo=UTC))

    assert payload["collection_estimate"]["feasibility"] == "TOO_SLOW_FOR_LIVE_ONLY_COLLECTION"
    assert payload["collection_estimate"]["estimated_days_to_sample_gate"] > 300
    assert "historical_signal_rate_makes_live_only_collection_too_slow" in payload["blockers"]


def test_review_aggregates_base_signal_rejection_reasons(tmp_path: Path) -> None:
    contract = tmp_path / "contract.json"
    _write_contract(contract)
    report = tmp_path / "watch.json"
    _write_watch_report(
        report,
        generated_at="2026-05-18T14:00:00+00:00",
        candidates=[],
        base_signals=[
            _base_signal(
                "BTCUSDT",
                "2026-05-18T07:01:00+00:00",
                ["direction_mismatch", "setup_hour_not_allowed"],
            ),
            _base_signal(
                "ETHUSDT",
                "2026-05-18T13:01:00+00:00",
                ["volume_factor_below_contract"],
            ),
        ],
    )

    payload = review.build_payload(contract, [report], generated_at=datetime(2026, 5, 18, tzinfo=UTC))

    rejection_summary = payload["base_signal_rejection_summary"]
    assert payload["base_signal_summary"]["count"] == 2
    assert rejection_summary["rejected_count"] == 2
    assert rejection_summary["by_filter_reason"] == {
        "direction_mismatch": 1,
        "setup_hour_not_allowed": 1,
        "volume_factor_below_contract": 1,
    }
    assert rejection_summary["by_primary_filter_reason"] == {
        "direction_mismatch": 1,
        "volume_factor_below_contract": 1,
    }


def test_report_paths_accepts_shell_expanded_glob_tail(tmp_path: Path) -> None:
    first = tmp_path / "watch_1.json"
    second = tmp_path / "watch_2.json"
    first.write_text("{}", encoding="utf-8")
    second.write_text("{}", encoding="utf-8")

    paths = review._report_paths(str(first), [str(second)])

    assert paths == [first, second]
