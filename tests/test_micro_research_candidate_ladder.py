from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from scripts import run_micro_research_candidate_ladder as ladder


def _observation(
    *,
    days: int,
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"),
    entry_timing_model: str = "intrabar_1m_confirm_next_open",
    total_r: float = 10.0,
    ev_r: float = 0.10,
    profit_to_dd: float = 1.2,
    positive_symbol_fraction: float = 0.75,
    positive_year_fraction: float = 1.0,
) -> ladder.CandidateObservation:
    return ladder.CandidateObservation(
        source_path="example.json",
        schema_version="micro_main_intrabar_research_v1",
        generated_at="2026-05-18T00:00:00+00:00",
        family="session_impulse_retest_intrabar",
        policy_name="example_policy",
        days=days,
        symbols=symbols,
        entry_timing_model=entry_timing_model,
        no_lookahead=entry_timing_model in ladder.NO_LOOKAHEAD_ENTRY_MODELS,
        summary={
            "closed": 120,
            "total_r": total_r,
            "gross_r": total_r + 5.0,
            "ev_r": ev_r,
            "win_rate": 0.55,
            "max_dd_r": 8.0,
            "profit_to_dd": profit_to_dd,
            "symbol_count": len(symbols),
            "positive_symbol_fraction": positive_symbol_fraction,
            "year_count": 3 if days >= 1095 else 1,
            "positive_year_fraction": positive_year_fraction,
            "by_year_total_r": {"2024": 2.0, "2025": 3.0, "2026": 5.0} if days >= 1095 else {"2026": total_r},
        },
    )


def test_decision_rejects_unknown_or_legacy_timing() -> None:
    decision, reasons = ladder._decision(
        _observation(days=1095, entry_timing_model="", total_r=100.0, ev_r=0.5)
    )

    assert decision == "REJECT"
    assert "not_no_lookahead_protocol" in reasons


def test_decision_keeps_short_positive_horizon_shadow_only() -> None:
    decision, reasons = ladder._decision(_observation(days=90, total_r=5.0, ev_r=0.08))

    assert decision == "SHADOW_ONLY"
    assert "positive_but_not_promotable" in reasons


def test_decision_keeps_single_symbol_long_result_shadow_only() -> None:
    decision, reasons = ladder._decision(
        _observation(
            days=1825,
            symbols=("ADAUSDT",),
            total_r=6.6,
            ev_r=0.03,
            positive_symbol_fraction=1.0,
            positive_year_fraction=0.83,
        )
    )

    assert decision == "SHADOW_ONLY"
    assert "single_symbol_positive_only" in reasons


def test_decision_requires_multi_symbol_consistency_for_live_review() -> None:
    decision, reasons = ladder._decision(
        _observation(
            days=1095,
            symbols=(
                "BTCUSDT",
                "ETHUSDT",
                "SOLUSDT",
                "BNBUSDT",
                "XRPUSDT",
                "ADAUSDT",
                "AVAXUSDT",
                "LINKUSDT",
            ),
            total_r=80.0,
            ev_r=0.12,
            profit_to_dd=1.4,
            positive_symbol_fraction=0.75,
            positive_year_fraction=1.0,
        )
    )

    assert decision == "LIVE_CANDIDATE_REVIEW"
    assert reasons == ["passes_long_horizon_multi_symbol_review_gate"]


def test_build_payload_counts_decisions(monkeypatch, tmp_path: Path) -> None:
    good = _observation(days=90, total_r=5.0, ev_r=0.08)
    bad = _observation(days=365, total_r=-1.0, ev_r=-0.01)
    monkeypatch.setattr(ladder, "_observations_from_report", lambda _path: [good, bad])

    payload = ladder.build_payload([tmp_path / "fake.json"], generated_at=datetime(2026, 5, 18, tzinfo=UTC))

    assert payload["authority"] == "research_only_no_live_authority_change"
    assert payload["decision_counts"] == {"REJECT": 1, "SHADOW_ONLY": 1}
    assert payload["observations"][0]["decision"] == "SHADOW_ONLY"


def test_intrabar_subset_report_is_parsed_as_paper_candidate(tmp_path: Path) -> None:
    report = tmp_path / "subset.json"
    report.write_text(
        """
        {
          "schema_version": "micro_main_intrabar_subset_report_v1",
          "generated_at": "2026-05-18T00:00:00+00:00",
          "source_scope": {
            "days": 1825,
            "symbols": ["BTCUSDT", "ETHUSDT", "LINKUSDT", "DOGEUSDT"],
            "entry_timing_model": "intrabar_1m_confirm_next_open"
          },
          "results": [
            {
              "name": "volume12_hour13_14_long",
              "summary": {
                "closed": 155,
                "total_r": 14.57,
                "gross_r": 20.0,
                "ev_r": 0.094,
                "win_rate": 0.45,
                "max_dd_r": 8.39,
                "profit_to_dd": 1.73,
                "symbol_count": 4,
                "positive_symbol_fraction": 0.75,
                "year_count": 6,
                "positive_year_fraction": 0.8333,
                "by_year_total_r": {"2021": -4.36, "2022": 3.9, "2023": 0.86, "2024": 2.61, "2025": 7.73, "2026": 3.81}
              },
              "by_symbol_total_r": {
                "BTCUSDT": 6.44,
                "DOGEUSDT": 7.72,
                "ETHUSDT": -0.07,
                "LINKUSDT": 0.47
              }
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    observations = ladder._observations_from_report(report)
    row = ladder._observation_row(observations[0])

    assert row["family"] == "session_impulse_retest_intrabar_subset"
    assert row["policy_name"] == "volume12_hour13_14_long"
    assert row["no_lookahead"] is True
    assert row["symbol_count"] == 4
    assert row["decision"] == "PAPER_CANDIDATE"


def test_intrabar_subset_report_rejects_moderate_fee_stress_failure(tmp_path: Path) -> None:
    report = tmp_path / "subset_fee.json"
    report.write_text(
        """
        {
          "schema_version": "micro_main_intrabar_subset_report_v1",
          "generated_at": "2026-05-18T00:00:00+00:00",
          "source_scope": {
            "days": 1825,
            "symbols": ["BTCUSDT", "ETHUSDT", "LINKUSDT", "DOGEUSDT"],
            "entry_timing_model": "intrabar_1m_confirm_next_open"
          },
          "results": [
            {
              "name": "body025_hour13_14_long",
              "summary": {
                "closed": 246,
                "total_r": 12.28,
                "gross_r": 20.0,
                "ev_r": 0.05,
                "win_rate": 0.44,
                "max_dd_r": 12.6,
                "profit_to_dd": 0.97,
                "symbol_count": 4,
                "positive_symbol_fraction": 0.75,
                "year_count": 6,
                "positive_year_fraction": 0.8333,
                "by_year_total_r": {"2021": -6.0, "2022": 2.0, "2023": 3.0, "2024": 0.1, "2025": 8.0, "2026": 3.0}
              },
              "cost_stress": {
                "extra_0_05r_per_trade": {"total_r": -0.01},
                "cost_x2_0": {"total_r": -17.4}
              },
              "by_symbol_total_r": {
                "BTCUSDT": 4.6,
                "DOGEUSDT": 6.9,
                "ETHUSDT": -8.3,
                "LINKUSDT": 8.9
              }
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    row = ladder._observation_row(ladder._observations_from_report(report)[0])

    assert row["decision"] == "REJECT"
    assert "fee_stress_extra_0_05r_non_positive" in row["reasons"]
    assert "fee_stress_cost_x2_non_positive" in row["reasons"]


def test_intrabar_subset_report_splits_policy_breakdowns(tmp_path: Path) -> None:
    report = tmp_path / "subset_by_policy.json"
    report.write_text(
        """
        {
          "schema_version": "micro_main_intrabar_subset_report_v1",
          "generated_at": "2026-05-18T00:00:00+00:00",
          "source_scope": {
            "days": 1825,
            "symbols": ["BTCUSDT", "ETHUSDT", "LINKUSDT", "DOGEUSDT"],
            "entry_timing_model": "intrabar_1m_confirm_next_open"
          },
          "results": [
            {
              "name": "volume12_body025_hour13_14_long",
              "by_policy": [
                {
                  "policy": "exit_a",
                  "summary": {
                    "closed": 120,
                    "total_r": 18.0,
                    "gross_r": 25.0,
                    "ev_r": 0.15,
                    "win_rate": 0.50,
                    "max_dd_r": 7.0,
                    "profit_to_dd": 2.57,
                    "symbol_count": 4,
                    "positive_symbol_fraction": 0.75,
                    "year_count": 6,
                    "positive_year_fraction": 0.8333
                  },
                  "cost_stress": {
                    "extra_0_05r_per_trade": {"total_r": 12.0},
                    "cost_x2_0": {"total_r": 2.0}
                  },
                  "by_symbol_total_r": {
                    "BTCUSDT": 6.0,
                    "DOGEUSDT": 7.0,
                    "ETHUSDT": -1.0,
                    "LINKUSDT": 6.0
                  },
                  "by_year_total_r": {"2021": -1.0, "2022": 3.0, "2023": 2.0, "2024": 4.0, "2025": 5.0, "2026": 5.0}
                },
                {
                  "policy": "exit_b",
                  "summary": {
                    "closed": 120,
                    "total_r": 10.0,
                    "gross_r": 18.0,
                    "ev_r": 0.083,
                    "win_rate": 0.45,
                    "max_dd_r": 8.0,
                    "profit_to_dd": 1.25,
                    "symbol_count": 4,
                    "positive_symbol_fraction": 0.75,
                    "year_count": 6,
                    "positive_year_fraction": 0.8333
                  },
                  "cost_stress": {
                    "extra_0_05r_per_trade": {"total_r": 4.0},
                    "cost_x2_0": {"total_r": -1.0}
                  },
                  "by_symbol_total_r": {
                    "BTCUSDT": 4.0,
                    "DOGEUSDT": 4.0,
                    "ETHUSDT": -2.0,
                    "LINKUSDT": 4.0
                  },
                  "by_year_total_r": {"2021": -1.0, "2022": 2.0, "2023": 2.0, "2024": 2.0, "2025": 3.0, "2026": 2.0}
                }
              ]
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    rows = [ladder._observation_row(item) for item in ladder._observations_from_report(report)]

    assert len(rows) == 2
    assert rows[0]["source_policy_names"] == ["exit_a"]
    assert rows[1]["source_policy_names"] == ["exit_b"]
    assert rows[0]["policy_name"] == "volume12_body025_hour13_14_long"


def test_expand_report_paths_uses_explicit_paths_without_default_globs(tmp_path: Path) -> None:
    explicit = tmp_path / "explicit.json"
    explicit.write_text("{}", encoding="utf-8")

    paths = ladder._expand_report_paths([str(explicit)], [])

    assert paths == [explicit]
