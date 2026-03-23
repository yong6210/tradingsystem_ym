from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.core.config import get_settings
from app.services.portfolio_risk_overlay import PortfolioRiskOverlayService
from app.services.thesis_fingerprint import ThesisFingerprintService


class _CandleRepoStub:
    def __init__(self, closes_by_symbol: dict[str, list[float]]):
        self.closes_by_symbol = closes_by_symbol

    def list_recent(self, symbol: str, timeframe: str, limit: int = 300) -> list[SimpleNamespace]:
        closes = list(self.closes_by_symbol.get(symbol, []))
        closes = closes[-limit:]
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        rows: list[SimpleNamespace] = []
        for i, close in enumerate(closes):
            rows.append(SimpleNamespace(ts=start + timedelta(minutes=5 * i), c=float(close)))
        return rows


def _with_overlay_settings() -> dict[str, float | int | bool]:
    return {
        "portfolio_overlay_enabled": True,
        "portfolio_overlay_window_bars": 20,
        "portfolio_overlay_min_overlap_bars": 4,
        "portfolio_overlay_high_corr_threshold": 0.8,
        "portfolio_overlay_max_total_exposure": 10,
        "portfolio_overlay_max_directional_exposure": 10,
        "portfolio_overlay_max_cluster_exposure": 1,
        "portfolio_overlay_penalty_per_high_corr": 0.0,
        "portfolio_overlay_penalty_corr_scale": 0.0,
        "portfolio_overlay_min_risk_budget_score": 0.0,
        "portfolio_overlay_volatility_target": 0.01,
        "portfolio_overlay_volatility_hard_cap": 0.03,
        "portfolio_overlay_penalty_volatility_scale": 12.0,
        "portfolio_overlay_penalty_exposure_scale": 10.0,
        "portfolio_overlay_regime_penalty_range": 0.0,
        "portfolio_overlay_regime_penalty_trend": 4.0,
        "portfolio_overlay_regime_penalty_shock": 12.0,
        "portfolio_overlay_cap_multiplier_range": 1.0,
        "portfolio_overlay_cap_multiplier_trend": 0.75,
        "portfolio_overlay_cap_multiplier_shock": 0.5,
    }


def test_portfolio_overlay_blocks_high_corr_cluster() -> None:
    settings = get_settings()
    updates = _with_overlay_settings()
    old_values = {k: getattr(settings, k) for k in updates}

    try:
        for key, value in updates.items():
            setattr(settings, key, value)

        candle_repo = _CandleRepoStub(
            {
                "AAAUSDC": [100, 102, 101, 103, 102, 104, 103],
                "BBBUSDC": [200, 204, 202, 206, 204, 208, 206],
                "CCCUSDC": [100, 98, 99, 97, 98, 96, 97],
            }
        )
        service = PortfolioRiskOverlayService(candle_repo=candle_repo, settings=settings)
        rows = [
            {"symbol": "AAAUSDC", "direction": "long", "final_rank_score": 100.0},
            {"symbol": "BBBUSDC", "direction": "long", "final_rank_score": 95.0},
            {"symbol": "CCCUSDC", "direction": "long", "final_rank_score": 90.0},
        ]

        filtered = service.filter_rows(rows, limit=10, existing_exposures=[])
        symbols = [row["symbol"] for row in filtered]

        assert symbols == ["AAAUSDC", "CCCUSDC"]
    finally:
        for key, value in old_values.items():
            setattr(settings, key, value)


def test_portfolio_overlay_respects_directional_limit() -> None:
    settings = get_settings()
    updates = _with_overlay_settings()
    updates["portfolio_overlay_max_directional_exposure"] = 1
    updates["portfolio_overlay_max_cluster_exposure"] = 99
    old_values = {k: getattr(settings, k) for k in updates}

    try:
        for key, value in updates.items():
            setattr(settings, key, value)

        service = PortfolioRiskOverlayService(candle_repo=_CandleRepoStub({}), settings=settings)
        rows = [
            {"symbol": "AAAUSDC", "direction": "long", "final_rank_score": 100.0},
            {"symbol": "BBBUSDC", "direction": "long", "final_rank_score": 96.0},
            {"symbol": "CCCUSDC", "direction": "short", "final_rank_score": 92.0},
        ]

        filtered = service.filter_rows(rows, limit=10, existing_exposures=[])
        symbols = [row["symbol"] for row in filtered]
        assert symbols == ["AAAUSDC", "CCCUSDC"]
    finally:
        for key, value in old_values.items():
            setattr(settings, key, value)


def test_portfolio_overlay_accounts_for_existing_exposure() -> None:
    settings = get_settings()
    updates = _with_overlay_settings()
    updates["portfolio_overlay_max_total_exposure"] = 1
    old_values = {k: getattr(settings, k) for k in updates}

    try:
        for key, value in updates.items():
            setattr(settings, key, value)

        service = PortfolioRiskOverlayService(candle_repo=_CandleRepoStub({}), settings=settings)
        rows = [
            {"symbol": "AAAUSDC", "direction": "long", "final_rank_score": 100.0},
            {"symbol": "CCCUSDC", "direction": "short", "final_rank_score": 90.0},
        ]

        filtered = service.filter_rows(rows, limit=10, existing_exposures=[("BTCUSDC", "long")])
        assert filtered == []
    finally:
        for key, value in old_values.items():
            setattr(settings, key, value)


def test_portfolio_overlay_shock_regime_tightens_caps() -> None:
    settings = get_settings()
    updates = _with_overlay_settings()
    updates["portfolio_overlay_max_total_exposure"] = 2
    updates["portfolio_overlay_max_directional_exposure"] = 2
    updates["portfolio_overlay_max_cluster_exposure"] = 2
    updates["portfolio_overlay_cap_multiplier_shock"] = 0.5
    old_values = {k: getattr(settings, k) for k in updates}

    try:
        for key, value in updates.items():
            setattr(settings, key, value)

        service = PortfolioRiskOverlayService(candle_repo=_CandleRepoStub({}), settings=settings)
        rows = [
            {"symbol": "AAAUSDC", "direction": "long", "regime": "shock", "final_rank_score": 100.0},
            {"symbol": "BBBUSDC", "direction": "short", "regime": "range", "final_rank_score": 95.0},
        ]

        filtered = service.filter_rows(rows, limit=10, existing_exposures=[("BTCUSDC", "long")])
        assert [row["symbol"] for row in filtered] == ["BBBUSDC"]
        assert filtered[0]["portfolio_total_cap"] == 2
        assert filtered[0]["portfolio_directional_cap"] == 2
        assert filtered[0]["portfolio_cluster_cap"] == 2
    finally:
        for key, value in old_values.items():
            setattr(settings, key, value)


def test_portfolio_overlay_penalizes_high_volatility_candidates() -> None:
    settings = get_settings()
    updates = _with_overlay_settings()
    updates["portfolio_overlay_max_cluster_exposure"] = 99
    updates["portfolio_overlay_high_corr_threshold"] = 0.999
    updates["portfolio_overlay_penalty_corr_scale"] = 0.0
    updates["portfolio_overlay_penalty_per_high_corr"] = 0.0
    updates["portfolio_overlay_penalty_volatility_scale"] = 2.0
    old_values = {k: getattr(settings, k) for k in updates}

    try:
        for key, value in updates.items():
            setattr(settings, key, value)

        candle_repo = _CandleRepoStub(
            {
                "STABLEUSDC": [100.0, 100.2, 100.1, 100.3, 100.2, 100.4, 100.3],
                "VOLAUSDC": [100.0, 110.0, 90.0, 112.0, 88.0, 115.0, 85.0],
            }
        )
        service = PortfolioRiskOverlayService(candle_repo=candle_repo, settings=settings)
        rows = [
            {"symbol": "VOLAUSDC", "direction": "long", "regime": "range", "final_rank_score": 101.0},
            {"symbol": "STABLEUSDC", "direction": "long", "regime": "range", "final_rank_score": 100.0},
        ]

        filtered = service.filter_rows(rows, limit=10, existing_exposures=[])
        assert [row["symbol"] for row in filtered] == ["STABLEUSDC", "VOLAUSDC"]
        assert filtered[0]["risk_budget_score"] > filtered[1]["risk_budget_score"]
        assert filtered[1]["portfolio_volatility"] > filtered[0]["portfolio_volatility"]
        assert filtered[1]["portfolio_penalty"] > filtered[0]["portfolio_penalty"]
    finally:
        for key, value in old_values.items():
            setattr(settings, key, value)


def test_portfolio_overlay_clamps_recommended_risk_when_family_outcome_degrades() -> None:
    settings = get_settings()
    updates = _with_overlay_settings()
    updates["portfolio_overlay_max_cluster_exposure"] = 99
    updates["portfolio_overlay_max_directional_exposure"] = 99
    updates["portfolio_overlay_max_total_exposure"] = 99
    old_values = {k: getattr(settings, k) for k in updates}

    try:
        for key, value in updates.items():
            setattr(settings, key, value)

        service = PortfolioRiskOverlayService(candle_repo=_CandleRepoStub({}), settings=settings)
        assessed = service.assess_rows(
            [
                {
                    "symbol": "AAAUSDC",
                    "direction": "long",
                    "regime": "trend",
                    "strategy_family": "trend_continuation",
                    "strategy_grade": "A",
                    "entry_model": "CONFIRM",
                    "expected_ev_r": 0.8,
                    "final_rank_score": 100.0,
                    "validity": {
                        "strategy_family": "trend_continuation",
                        "strategy_grade": "A",
                        "regime": "trend",
                        "reaction_classification": "rejection_confirmed",
                    },
                    "session_guidance": {"state": "london", "session_name": "london"},
                }
            ],
            existing_exposures=[],
            outcome_inputs_by_symbol={
                "AAAUSDC": {
                    "family_execution_degradation_advisory_summary": {
                        "families": [
                            {
                                "family": "trend_continuation",
                                "status": "manual_review",
                                "confidence": "high",
                                "sample_note": "family closed sample is sufficient for advisory use",
                            }
                        ]
                    },
                    "mode_advisory_summary": {"family": [], "regime": [], "session": []},
                    "score_to_outcome_funnel_summary": {
                        "decomposition": {
                            "family": [
                                {
                                    "key": "trend_continuation",
                                    "closed": 6,
                                    "baseline_cost_profitable_rate_from_closed": 0.2,
                                }
                            ],
                            "regime": [],
                            "session": [],
                        }
                    },
                }
            },
        )

        adjustment = assessed[0]["strategy_sizing"]["outcome_risk_adjustment"]
        assert adjustment["applied"] is True
        assert adjustment["penalty_tier"] == "hard_clamp"
        assert adjustment["multiplier"] == 0.5
        assert assessed[0]["recommended_risk_r"] == adjustment["final_risk_r"]
        assert assessed[0]["recommended_risk_r"] == round(adjustment["base_final_risk_r"] * 0.5, 4)
    finally:
        for key, value in old_values.items():
            setattr(settings, key, value)


def test_portfolio_overlay_outcome_bias_reorders_accepted_candidates() -> None:
    settings = get_settings()
    updates = _with_overlay_settings()
    updates["portfolio_overlay_max_cluster_exposure"] = 99
    updates["portfolio_overlay_max_directional_exposure"] = 99
    updates["portfolio_overlay_max_total_exposure"] = 99
    old_values = {k: getattr(settings, k) for k in updates}

    try:
        for key, value in updates.items():
            setattr(settings, key, value)

        service = PortfolioRiskOverlayService(candle_repo=_CandleRepoStub({}), settings=settings)
        filtered = service.filter_rows(
            [
                {
                    "symbol": "AAAUSDC",
                    "direction": "long",
                    "regime": "trend",
                    "strategy_family": "trend_continuation",
                    "strategy_grade": "A",
                    "entry_model": "CONFIRM",
                    "expected_ev_r": 0.8,
                    "final_rank_score": 100.0,
                    "session_guidance": {"state": "london", "session_name": "london"},
                    "validity": {
                        "strategy_family": "trend_continuation",
                        "strategy_grade": "A",
                        "regime": "trend",
                        "reaction_classification": "rejection_confirmed",
                    },
                },
                {
                    "symbol": "BBBUSDC",
                    "direction": "long",
                    "regime": "trend",
                    "strategy_family": "sweep_reversal",
                    "strategy_grade": "A",
                    "entry_model": "CONFIRM",
                    "expected_ev_r": 0.8,
                    "final_rank_score": 98.0,
                    "session_guidance": {"state": "london", "session_name": "london"},
                    "validity": {
                        "strategy_family": "sweep_reversal",
                        "strategy_grade": "A",
                        "regime": "trend",
                        "reaction_classification": "rejection_confirmed",
                    },
                },
            ],
            limit=10,
            existing_exposures=[],
            outcome_inputs_by_symbol={
                "AAAUSDC": {
                    "family_execution_degradation_advisory_summary": {
                        "families": [
                            {
                                "family": "trend_continuation",
                                "status": "manual_review",
                                "confidence": "high",
                                "sample_note": "family closed sample is sufficient for advisory use",
                            }
                        ]
                    },
                    "mode_advisory_summary": {"family": [], "regime": [], "session": []},
                    "score_to_outcome_funnel_summary": {
                        "decomposition": {
                            "family": [
                                {
                                    "key": "trend_continuation",
                                    "closed": 6,
                                    "baseline_cost_profitable_rate_from_closed": 0.2,
                                }
                            ],
                            "regime": [],
                            "session": [],
                        }
                    },
                },
                "BBBUSDC": {
                    "family_execution_degradation_advisory_summary": {
                        "families": [
                            {
                                "family": "sweep_reversal",
                                "status": "healthy",
                                "confidence": "high",
                                "sample_note": "family closed sample is sufficient for advisory use",
                            }
                        ]
                    },
                    "mode_advisory_summary": {"family": [], "regime": [], "session": []},
                    "score_to_outcome_funnel_summary": {
                        "decomposition": {
                            "family": [
                                {
                                    "key": "sweep_reversal",
                                    "closed": 8,
                                    "baseline_cost_profitable_rate_from_closed": 0.6,
                                }
                            ],
                            "regime": [],
                            "session": [],
                        }
                    },
                },
            },
            apply_outcome_bias=True,
        )

        assert [row["symbol"] for row in filtered[:2]] == ["BBBUSDC", "AAAUSDC"]
        assert filtered[0]["outcome_bias"]["tier"] == "positive"
        assert filtered[1]["outcome_bias"]["tier"] == "negative"
        assert filtered[0]["post_outcome_final_rank_score"] > filtered[1]["post_outcome_final_rank_score"]
    finally:
        for key, value in old_values.items():
            setattr(settings, key, value)


def test_portfolio_overlay_builds_capital_allocator_and_allocated_risk() -> None:
    settings = get_settings()
    updates = _with_overlay_settings()
    updates["portfolio_overlay_max_cluster_exposure"] = 99
    updates["portfolio_overlay_max_directional_exposure"] = 99
    updates["portfolio_overlay_max_total_exposure"] = 99
    old_values = {k: getattr(settings, k) for k in updates}

    try:
        for key, value in updates.items():
            setattr(settings, key, value)

        service = PortfolioRiskOverlayService(candle_repo=_CandleRepoStub({}), settings=settings)
        assessed = service.assess_rows(
            [
                {
                    "symbol": "AAAUSDC",
                    "direction": "long",
                    "regime": "trend",
                    "strategy_family": "sweep_reversal",
                    "strategy_grade": "A",
                    "entry_model": "CONFIRM",
                    "expected_ev_r": 0.8,
                    "final_rank_score": 100.0,
                    "session_guidance": {"state": "london", "session_name": "london"},
                    "validity": {
                        "strategy_family": "sweep_reversal",
                        "strategy_grade": "A",
                        "regime": "trend",
                        "reaction_classification": "rejection_confirmed",
                    },
                },
                {
                    "symbol": "BBBUSDC",
                    "direction": "short",
                    "regime": "range",
                    "strategy_family": "trend_continuation",
                    "strategy_grade": "A",
                    "entry_model": "CONFIRM",
                    "expected_ev_r": 0.8,
                    "final_rank_score": 98.0,
                    "session_guidance": {"state": "dead_session", "session_name": "dead_session"},
                    "validity": {
                        "strategy_family": "trend_continuation",
                        "strategy_grade": "A",
                        "regime": "range",
                        "reaction_classification": "rejection_confirmed",
                    },
                },
            ],
            existing_exposures=[],
            outcome_inputs_by_symbol={
                "AAAUSDC": {
                    "family_execution_degradation_advisory_summary": {
                        "families": [
                            {
                                "family": "sweep_reversal",
                                "status": "healthy",
                                "confidence": "high",
                                "sample_note": "family closed sample is sufficient for advisory use",
                            }
                        ]
                    },
                    "mode_advisory_summary": {
                        "family": [{"bucket": "sweep_reversal", "advisory_state": "keep_current_mode", "confidence": "medium"}],
                        "regime": [{"bucket": "trend", "advisory_state": "keep_current_mode", "confidence": "medium"}],
                        "session": [{"bucket": "london", "advisory_state": "keep_current_mode", "confidence": "medium"}],
                    },
                    "score_to_outcome_funnel_summary": {
                        "decomposition": {
                            "family": [{"key": "sweep_reversal", "closed": 12, "baseline_cost_profitable_rate_from_closed": 0.6}],
                            "regime": [{"key": "trend", "closed": 8, "baseline_cost_profitable_rate_from_closed": 0.55}],
                            "session": [{"key": "london", "closed": 6, "baseline_cost_profitable_rate_from_closed": 0.55}],
                        }
                    },
                },
                "BBBUSDC": {
                    "family_execution_degradation_advisory_summary": {
                        "families": [
                            {
                                "family": "trend_continuation",
                                "status": "healthy",
                                "confidence": "low",
                                "sample_note": "family sample is thin; treat this as advisory context only",
                            }
                        ]
                    },
                    "mode_advisory_summary": {"family": [], "regime": [], "session": []},
                    "score_to_outcome_funnel_summary": {
                        "decomposition": {
                            "family": [{"key": "trend_continuation", "closed": 2, "baseline_cost_profitable_rate_from_closed": 1.0}],
                            "regime": [],
                            "session": [],
                        }
                    },
                },
            },
        )

        positive = next(row for row in assessed if row["symbol"] == "AAAUSDC")
        thin = next(row for row in assessed if row["symbol"] == "BBBUSDC")

        assert positive["capital_allocator"]["tier"] == "boost"
        assert positive["allocation_weight"] > 1.0
        assert positive["allocated_risk_r"] > positive["recommended_risk_r"]
        assert positive["capital_pressure"] in {"neutral", "underallocated_positive"}

        assert thin["capital_allocator"]["tier"] == "neutral"
        assert thin["capital_allocator"]["maturity"] == "thin_sample"
        assert thin["allocated_risk_r"] == thin["recommended_risk_r"]
    finally:
        for key, value in old_values.items():
            setattr(settings, key, value)


def test_portfolio_overlay_blocks_duplicate_thesis_cluster() -> None:
    settings = get_settings()
    updates = _with_overlay_settings()
    updates["portfolio_overlay_max_cluster_exposure"] = 99
    updates["thesis_dedupe_enabled"] = True
    updates["thesis_max_active_clusters"] = 2
    old_values = {k: getattr(settings, k) for k in updates}
    thesis = ThesisFingerprintService()

    try:
        for key, value in updates.items():
            setattr(settings, key, value)

        service = PortfolioRiskOverlayService(candle_repo=_CandleRepoStub({}), settings=settings)
        first_fp = thesis.build(
            symbol="BTCAUSDC",
            direction="short",
            regime="trend",
            strategy_family="sweep_reversal",
            reaction_classification="rejection_confirmed",
            zone_type="OB",
            near_lp=False,
            at=datetime(2026, 3, 7, 9, 5, tzinfo=timezone.utc),
        )
        second_fp = thesis.build(
            symbol="BTCBUSDC",
            direction="short",
            regime="trend",
            strategy_family="sweep_reversal",
            reaction_classification="rejection_tentative",
            zone_type="LP",
            near_lp=True,
            at=datetime(2026, 3, 7, 9, 35, tzinfo=timezone.utc),
        )
        assessed = service.assess_rows(
            [
                {
                    "symbol": "BTCAUSDC",
                    "direction": "short",
                    "regime": "trend",
                    "strategy_family": "sweep_reversal",
                    "final_rank_score": 100.0,
                    "thesis_fingerprint": first_fp,
                },
                {
                    "symbol": "BTCBUSDC",
                    "direction": "short",
                    "regime": "trend",
                    "strategy_family": "sweep_reversal",
                    "final_rank_score": 96.0,
                    "thesis_fingerprint": second_fp,
                },
            ],
            existing_exposures=[],
        )

        assert assessed[0]["accepted"] is True
        assert assessed[1]["accepted"] is False
        assert assessed[1]["block_reason"] == "thesis_duplicate_blocked"
        assert assessed[1]["block_reason_message"] == "Blocked: an active candidate with the same thesis already exists."
        assert assessed[1]["thesis_primary_symbol"] == "BTCAUSDC"
    finally:
        for key, value in old_values.items():
            setattr(settings, key, value)


def test_portfolio_overlay_blocks_new_thesis_when_active_cap_is_hit() -> None:
    settings = get_settings()
    updates = _with_overlay_settings()
    updates["portfolio_overlay_max_cluster_exposure"] = 99
    updates["portfolio_overlay_high_corr_threshold"] = 0.999
    updates["thesis_dedupe_enabled"] = True
    updates["thesis_max_active_clusters"] = 2
    old_values = {k: getattr(settings, k) for k in updates}
    thesis = ThesisFingerprintService()

    try:
        for key, value in updates.items():
            setattr(settings, key, value)

        service = PortfolioRiskOverlayService(candle_repo=_CandleRepoStub({}), settings=settings)
        existing_exposures = [
            {
                "symbol": "BTCAUSDC",
                "direction": "long",
                "regime": "trend",
                "strategy_family": "trend_continuation",
                "thesis_fingerprint": thesis.build(
                    symbol="BTCAUSDC",
                    direction="long",
                    regime="trend",
                    strategy_family="trend_continuation",
                    reaction_classification="acceptance_tentative",
                    zone_type="OB",
                    near_lp=False,
                    at=datetime(2026, 3, 7, 9, 5, tzinfo=timezone.utc),
                ),
            },
            {
                "symbol": "ETHAUSDC",
                "direction": "short",
                "regime": "range",
                "strategy_family": "range_rotation",
                "thesis_fingerprint": thesis.build(
                    symbol="ETHAUSDC",
                    direction="short",
                    regime="range",
                    strategy_family="range_rotation",
                    reaction_classification="rejection_confirmed",
                    zone_type="LP",
                    near_lp=True,
                    at=datetime(2026, 3, 7, 10, 5, tzinfo=timezone.utc),
                ),
            },
        ]
        assessed = service.assess_rows(
            [
                {
                    "symbol": "SOLAUSDC",
                    "direction": "long",
                    "regime": "trend",
                    "strategy_family": "trend_continuation",
                    "final_rank_score": 101.0,
                    "thesis_fingerprint": thesis.build(
                        symbol="SOLAUSDC",
                        direction="long",
                        regime="trend",
                        strategy_family="trend_continuation",
                        reaction_classification="acceptance_confirmed",
                        zone_type="OB",
                        near_lp=False,
                        at=datetime(2026, 3, 7, 11, 5, tzinfo=timezone.utc),
                    ),
                }
            ],
            existing_exposures=existing_exposures,
        )

        assert assessed[0]["accepted"] is False
        assert assessed[0]["block_reason"] == "thesis_active_cap_reached"
        assert assessed[0]["block_reason_message"] == "Blocked: active thesis cluster cap is reached."
        assert assessed[0]["thesis_rejected_reason"] == "active_thesis_cluster_cap"
    finally:
        for key, value in old_values.items():
            setattr(settings, key, value)


def test_portfolio_overlay_respects_mode_daily_trade_limit() -> None:
    settings = get_settings()
    updates = _with_overlay_settings()
    updates["strategy_mode"] = "A_ONLY"
    updates["strategy_mode_a_only_max_daily_trades"] = 1
    old_values = {k: getattr(settings, k) for k in updates}

    try:
        for key, value in updates.items():
            setattr(settings, key, value)

        service = PortfolioRiskOverlayService(candle_repo=_CandleRepoStub({}), settings=settings)
        assessed = service.assess_rows(
            [
                {
                    "symbol": "AAAUSDC",
                    "direction": "long",
                    "strategy_family": "sweep_reversal",
                    "strategy_grade": "A",
                    "entry_model": "CONFIRM",
                    "regime": "range",
                    "final_rank_score": 100.0,
                    "validity": {
                        "strategy_family": "sweep_reversal",
                        "strategy_grade": "A",
                        "reaction_classification": "rejection_confirmed",
                    },
                }
            ],
            existing_exposures=[],
            today_trade_count=1,
        )
        assert assessed[0]["accepted"] is False
        assert assessed[0]["block_reason"] == "mode_daily_trade_limit_reached"
    finally:
        for key, value in old_values.items():
            setattr(settings, key, value)


def test_portfolio_overlay_respects_mode_total_risk_cap() -> None:
    settings = get_settings()
    updates = _with_overlay_settings()
    updates["strategy_mode"] = "A_ONLY"
    updates["strategy_mode_a_only_max_total_risk_r"] = 1.0
    old_values = {k: getattr(settings, k) for k in updates}

    try:
        for key, value in updates.items():
            setattr(settings, key, value)

        service = PortfolioRiskOverlayService(candle_repo=_CandleRepoStub({}), settings=settings)
        assessed = service.assess_rows(
            [
                {
                    "symbol": "AAAUSDC",
                    "direction": "long",
                    "strategy_family": "sweep_reversal",
                    "strategy_grade": "A",
                    "entry_model": "LIMIT",
                    "regime": "trend",
                    "final_rank_score": 100.0,
                    "validity": {
                        "strategy_family": "sweep_reversal",
                        "strategy_grade": "A",
                        "reaction_classification": "rejection_confirmed",
                    },
                }
            ],
            existing_exposures=[
                {
                    "symbol": "BTCUSDC",
                    "direction": "long",
                    "recommended_risk_r": 0.7,
                }
            ],
            today_trade_count=0,
        )
        assert assessed[0]["accepted"] is False
        assert assessed[0]["block_reason"] == "mode_total_risk_cap_reached"
    finally:
        for key, value in old_values.items():
            setattr(settings, key, value)


def test_portfolio_overlay_attaches_session_guidance_without_hard_block() -> None:
    settings = get_settings()
    updates = _with_overlay_settings()
    updates["portfolio_overlay_max_cluster_exposure"] = 99
    updates["session_guidance_penalty_dead_session"] = 7.0
    old_values = {k: getattr(settings, k) for k in updates}

    try:
        for key, value in updates.items():
            setattr(settings, key, value)

        service = PortfolioRiskOverlayService(candle_repo=_CandleRepoStub({}), settings=settings)
        assessed = service.assess_rows(
            [
                {
                    "symbol": "AAAUSDC",
                    "direction": "long",
                    "strategy_family": "sweep_reversal",
                    "strategy_grade": "A",
                    "entry_model": "LIMIT",
                    "regime": "range",
                    "final_rank_score": 100.0,
                    "validity": {
                        "strategy_family": "sweep_reversal",
                        "strategy_grade": "A",
                        "reaction_classification": "rejection_confirmed",
                    },
                }
            ],
            existing_exposures=[],
            operating_lock={
                "current_session": {"name": "inactive", "active": False},
                "active": False,
                "scope": "none",
            },
        )

        assert assessed[0]["accepted"] is True
        assert assessed[0]["session_guidance"]["state"] == "dead_session"
        assert assessed[0]["session_penalty"] == 7.0
        assert assessed[0]["final_rank_score"] == assessed[0]["adjusted_rank_score"] - 7.0
        assert assessed[0]["session_guidance"]["engine_dead_session_hard_block"] is False
    finally:
        for key, value in old_values.items():
            setattr(settings, key, value)


def test_portfolio_overlay_routes_quality_near_miss_to_alpha_research() -> None:
    settings = get_settings()
    updates = _with_overlay_settings()
    updates["portfolio_overlay_min_risk_budget_score"] = 99.0
    updates["quality_gate_softening_enabled"] = True
    updates["alpha_research_pipeline_enabled"] = True
    updates["alpha_research_softened_risk_scale"] = 0.4
    old_values = {k: getattr(settings, k) for k in updates}

    try:
        for key, value in updates.items():
            setattr(settings, key, value)

        service = PortfolioRiskOverlayService(candle_repo=_CandleRepoStub({}), settings=settings)
        assessed = service.assess_rows(
            [
                {
                    "symbol": "AAAUSDC",
                    "direction": "long",
                    "strategy_family": "trend_continuation",
                    "strategy_grade": "A",
                    "entry_model": "LIMIT",
                    "regime": "range",
                    "final_rank_score": 100.0,
                    "expected_ev_r": 0.24,
                    "validity": {
                        "strategy_family": "trend_continuation",
                        "strategy_grade": "A",
                        "reaction_classification": "acceptance_confirmed",
                        "expected_ev_r": 0.24,
                    },
                }
            ],
            existing_exposures=[],
        )

        assert assessed[0]["accepted"] is False
        assert assessed[0]["block_reason"] == "risk_budget_below_min"
        assert assessed[0]["alpha_research_candidate"] is True
        assert assessed[0]["alpha_research_reason"] == "risk_budget_below_min"
        assert assessed[0]["alpha_research_softened_risk_r"] > 0.0
        assert assessed[0]["alpha_research_gap"] > 0.0
    finally:
        for key, value in old_values.items():
            setattr(settings, key, value)
